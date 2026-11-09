"""Unit tests for the factory PR scripts. No network access."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from unittest import mock

import gh_client
import open_pr
import pr_feedback
import pr_state
import publish_branch
import review_pr
from gh_client import GhError


def _failing_winreg():
    fake = mock.MagicMock()
    fake.OpenKey.side_effect = OSError("access denied")
    return fake


class PlanReviewTests(unittest.TestCase):
    def test_approve_with_protection_enables_automerge(self):
        self.assertEqual(
            review_pr.plan_review("approve", 0, True, 3),
            ["comment:approve", "status:success", "automerge:enable"],
        )

    def test_approve_without_protection_skips_automerge(self):
        self.assertEqual(
            review_pr.plan_review("approve", 0, False, 3),
            ["comment:approve", "status:success", "automerge:skipped-no-protection"],
        )

    def test_request_changes_below_limit(self):
        for prior in (0, 1, 2):
            with self.subTest(prior=prior):
                self.assertEqual(
                    review_pr.plan_review("request-changes", prior, True, 3),
                    ["comment:request-changes", "status:failure"],
                )

    def test_request_changes_at_limit_escalates(self):
        for prior in (3, 4):
            with self.subTest(prior=prior):
                self.assertEqual(
                    review_pr.plan_review("request-changes", prior, True, 3),
                    ["comment:escalate", "status:failure"],
                )

    def test_limit_of_one_escalates_on_second_request(self):
        self.assertEqual(
            review_pr.plan_review("request-changes", 1, False, 1),
            ["comment:escalate", "status:failure"],
        )

    def test_approve_below_limit_never_requests_changes_or_escalates(self):
        for prior in (0, 1, 2):
            for requires in (True, False):
                with self.subTest(prior=prior, requires=requires):
                    actions = review_pr.plan_review("approve", prior, requires, 3)
                    self.assertIn("comment:approve", actions)
                    self.assertNotIn("comment:request-changes", actions)
                    self.assertNotIn("comment:escalate", actions)
                    self.assertNotIn("status:failure", actions)

    def test_approve_at_or_above_limit_escalates_without_automerge(self):
        for prior in (3, 4, 5):
            for requires in (True, False):
                with self.subTest(prior=prior, requires=requires):
                    actions = review_pr.plan_review("approve", prior, requires, 3)
                    self.assertEqual(actions, ["comment:escalate", "status:failure"])
                    self.assertFalse(any(action.startswith("automerge") for action in actions))
                    self.assertNotIn("comment:approve", actions)

    def test_request_changes_never_enables_automerge(self):
        for prior in range(6):
            with self.subTest(prior=prior):
                actions = review_pr.plan_review("request-changes", prior, True, 3)
                self.assertFalse(any(action.startswith("automerge") for action in actions))

    def test_unknown_decision_raises(self):
        with self.assertRaises(ValueError):
            review_pr.plan_review("merge", 0, True, 3)


class ProtectionAndCommentTests(unittest.TestCase):
    def test_contexts_list_requires_status(self):
        protection = {"required_status_checks": {"contexts": ["test", "factory/review"]}}
        self.assertTrue(review_pr.protection_requires_status(protection))

    def test_contexts_without_status_does_not_require(self):
        protection = {"required_status_checks": {"contexts": ["test"]}}
        self.assertFalse(review_pr.protection_requires_status(protection))

    def test_checks_field_requires_status(self):
        protection = {"required_status_checks": {"contexts": [], "checks": [{"context": "factory/review"}]}}
        self.assertTrue(review_pr.protection_requires_status(protection))

    def test_missing_protection_does_not_require(self):
        self.assertFalse(review_pr.protection_requires_status(None))
        self.assertFalse(review_pr.protection_requires_status({}))

    def test_marker_is_first_line(self):
        self.assertEqual(
            review_pr.build_comment("approve", "Looks good", 0, 3),
            "<!-- factory-review:approve -->\nLooks good",
        )

    def test_escalation_says_human_must_decide(self):
        comment = review_pr.build_comment("escalate", "Still failing", 3, 3)
        self.assertEqual(comment.splitlines()[0], "<!-- factory-review:escalate -->")
        self.assertIn("A human must decide", comment)
        self.assertIn("not auto-merged", comment)

    def test_status_descriptions(self):
        self.assertEqual(review_pr.status_description("request-changes", 1, 3), "Changes requested (round 2 of 3)")
        self.assertEqual(review_pr.status_description("approve", 0, 3), "Approved by factory reviewer")
        self.assertEqual(
            review_pr.status_description("escalate", 3, 3),
            "Rework limit reached; human decision needed",
        )
        for kind in ("approve", "escalate", "request-changes"):
            self.assertLessEqual(len(review_pr.status_description(kind, 2, 3)), 140)


class BranchAndScopeTests(unittest.TestCase):
    def test_protected_branches_refused(self):
        for name in ("main", "master"):
            with self.subTest(name=name):
                self.assertTrue(publish_branch.validate_branch(name))

    def test_origin_prefix_refused(self):
        self.assertTrue(publish_branch.validate_branch("origin/factory/x"))

    def test_empty_and_dash_branch_refused(self):
        self.assertTrue(publish_branch.validate_branch(""))
        self.assertTrue(publish_branch.validate_branch("-f"))

    def test_feature_branch_allowed(self):
        self.assertEqual(publish_branch.validate_branch("TEST-1/short-slug"), [])

    def test_absolute_scopes_refused(self):
        for scope in ("/etc", "C:/products", "C:\\products", "\\\\server\\share"):
            with self.subTest(scope=scope):
                self.assertTrue(publish_branch.validate_scopes([scope]))

    def test_parent_scopes_refused(self):
        for scope in ("..\\x", "products/../x", ".."):
            with self.subTest(scope=scope):
                self.assertTrue(publish_branch.validate_scopes([scope]))

    def test_repo_root_scope_refused(self):
        for scope in (".", "./"):
            with self.subTest(scope=scope):
                self.assertTrue(publish_branch.validate_scopes([scope]))

    def test_valid_scopes_accepted(self):
        self.assertEqual(publish_branch.validate_scopes(["products/todo-app", "docs/designs/X-1.md"]), [])

    def test_no_scopes_refused(self):
        self.assertTrue(publish_branch.validate_scopes([]))

    def test_scope_prefix_accepts_inside_path(self):
        self.assertEqual(
            publish_branch.paths_within_scopes(["products/todo-app/x.ts"], ["products/todo-app"]),
            [],
        )

    def test_scope_prefix_rejects_outside_path(self):
        self.assertEqual(
            publish_branch.paths_within_scopes([".github/x.yml"], ["products/todo-app"]),
            [".github/x.yml"],
        )

    def test_scope_prefix_respects_directory_boundary(self):
        self.assertEqual(
            publish_branch.paths_within_scopes(["products/todo-application/a.ts"], ["products/todo-app"]),
            ["products/todo-application/a.ts"],
        )

    def test_exact_file_scope(self):
        self.assertEqual(publish_branch.paths_within_scopes(["README.md"], ["README.md"]), [])

    def test_backslash_paths_and_trailing_slash_scope(self):
        self.assertEqual(
            publish_branch.paths_within_scopes(["products\\todo-app\\x.ts"], ["products/todo-app/"]),
            [],
        )

    def test_only_outside_paths_returned(self):
        paths = ["products/todo-app/a.ts", ".github/workflows/ci.yml", "products/todo-app/b.ts"]
        self.assertEqual(
            publish_branch.paths_within_scopes(paths, ["products/todo-app"]),
            [".github/workflows/ci.yml"],
        )

    def test_dotdot_inside_a_name_is_allowed(self):
        self.assertEqual(publish_branch.validate_scopes(["products/a..b", "x..y/z"]), [])

    def test_dotdot_segment_refused_in_any_position(self):
        for scope in ("..", "../x", "x/..", "x\\..\\y", "x/../y"):
            with self.subTest(scope=scope):
                self.assertTrue(publish_branch.validate_scopes([scope]))

    def test_rename_out_of_scope_is_refused_with_no_renames_listing(self):
        # `git diff --cached --no-renames --name-only` reports both sides of a rename.
        # A rename from outside the scope into it must leave the outside side in the refused list.
        no_renames = ["products/x/a.txt", "outside/a.txt"]
        self.assertEqual(publish_branch.paths_within_scopes(no_renames, ["products/x"]), ["outside/a.txt"])

    def test_rename_detected_listing_would_hide_the_outside_side(self):
        # Shows why --no-renames is needed: the rename-detected listing names only the new path.
        detected = ["products/x/a.txt"]
        self.assertEqual(publish_branch.paths_within_scopes(detected, ["products/x"]), [])

    def test_parse_status_marks_staged_entries(self):
        output = " M products/x/b.txt\0M  outside/a.txt\0?? products/x/new/c.txt\0A  products/x/d.txt\0"
        self.assertEqual(
            publish_branch.parse_status(output),
            [
                (False, "products/x/b.txt"),
                (True, "outside/a.txt"),
                (False, "products/x/new/c.txt"),
                (True, "products/x/d.txt"),
            ],
        )


class PublishMainRefusalTests(unittest.TestCase):
    """Refusals must happen before any git command runs."""

    def _run(self, argv):
        with mock.patch.object(publish_branch, "_git", side_effect=AssertionError("git must not run")):
            return publish_branch.main(argv)

    def test_refuses_main(self):
        self.assertEqual(self._run(["--branch", "main", "--scope", "products/x", "--message", "m"]), 2)

    def test_refuses_master(self):
        self.assertEqual(self._run(["--branch", "master", "--scope", "products/x", "--message", "m"]), 2)

    def test_refuses_parent_scope(self):
        self.assertEqual(self._run(["--branch", "feat/x", "--scope", "../x", "--message", "m"]), 2)

    def test_refuses_absolute_scope(self):
        self.assertEqual(self._run(["--branch", "feat/x", "--scope", "C:/x", "--message", "m"]), 2)

    def test_refuses_empty_message(self):
        self.assertEqual(self._run(["--branch", "feat/x", "--scope", "products/x", "--message", "  "]), 2)


class OpenPrTests(unittest.TestCase):
    def test_trailing_newlines_are_stripped(self):
        self.assertEqual(open_pr.normalize_body("## Summary\n\nDone\n\n\n"), "## Summary\n\nDone")

    def test_empty_body_is_refused(self):
        for text in ("", "\n\n  \n"):
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    open_pr.normalize_body(text)

    def test_title_is_stripped_and_limited(self):
        self.assertEqual(open_pr.normalize_title("  TEST-1: add x  "), "TEST-1: add x")
        self.assertEqual(len(open_pr.normalize_title("x" * 256)), 256)
        with self.assertRaises(ValueError):
            open_pr.normalize_title("   ")
        with self.assertRaises(ValueError):
            open_pr.normalize_title("x" * 257)

    def test_main_refuses_main_head_before_any_call(self):
        with mock.patch.object(open_pr, "repo", side_effect=AssertionError("no API call")):
            self.assertEqual(open_pr.main(["--head", "main", "--title", "t", "--body-file", "missing.md"]), 2)


class ReviewBodyRefusalTests(unittest.TestCase):
    def test_missing_body_file_is_refused_before_api_call(self):
        with mock.patch.object(review_pr, "repo", side_effect=AssertionError("no API call")):
            code = review_pr.main(["--pr", "5", "--decision", "approve", "--body-file", "no-such-file.md"])
        self.assertEqual(code, 2)


class TokenTests(unittest.TestCase):
    def test_github_token_from_environment(self):
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": "ghp_envtoken"}, clear=True), \
                mock.patch.object(gh_client, "winreg", _failing_winreg()):
            self.assertEqual(gh_client.token(), "ghp_envtoken")

    def test_gh_token_is_fallback(self):
        with mock.patch.dict(os.environ, {"GH_TOKEN": "ghp_fallback"}, clear=True), \
                mock.patch.object(gh_client, "winreg", _failing_winreg()):
            self.assertEqual(gh_client.token(), "ghp_fallback")

    def test_registry_token_is_last_resort(self):
        fake = mock.MagicMock()
        fake.QueryValueEx.return_value = ("ghp_registry", 1)
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(gh_client, "winreg", fake):
            self.assertEqual(gh_client.token(), "ghp_registry")

    def test_missing_token_raises_without_secret_text(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(gh_client, "winreg", _failing_winreg()):
            with self.assertRaises(GhError) as ctx:
                gh_client.token()
        self.assertEqual(str(ctx.exception), "No GitHub token found in GITHUB_TOKEN or GH_TOKEN.")

    def test_missing_winreg_module_still_raises(self):
        with mock.patch.dict(os.environ, {}, clear=True), mock.patch.object(gh_client, "winreg", None):
            with self.assertRaises(GhError):
                gh_client.token()


class RepoTests(unittest.TestCase):
    def test_repo_from_environment(self):
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "ahsrah7/darkfactory_1"}, clear=True):
            self.assertEqual(gh_client.repo(), ("ahsrah7", "darkfactory_1"))

    def test_bad_environment_repo_raises(self):
        with mock.patch.dict(os.environ, {"GITHUB_REPOSITORY": "nope"}, clear=True):
            with self.assertRaises(GhError):
                gh_client.repo()

    def test_parse_https_remote(self):
        self.assertEqual(
            gh_client.parse_remote("https://github.com/ahsrah7/darkfactory_1.git\n"),
            ("ahsrah7", "darkfactory_1"),
        )

    def test_parse_ssh_remote(self):
        self.assertEqual(
            gh_client.parse_remote("git@github.com:ahsrah7/darkfactory_1.git"),
            ("ahsrah7", "darkfactory_1"),
        )

    def test_non_github_remote_refused_without_echoing_url(self):
        with self.assertRaises(GhError) as ctx:
            gh_client.parse_remote("https://user:secret@example.com/a/b.git")
        self.assertNotIn("secret", str(ctx.exception))
        self.assertNotIn("example.com", str(ctx.exception))


class RequestTests(unittest.TestCase):
    SECRET = "ghp_TESTSECRET123456"

    def test_error_message_masks_token_and_headers(self):
        body = json.dumps({"message": f"Bad credentials: {self.SECRET}"}).encode("utf-8")
        http_error = urllib.error.HTTPError("https://api.github.com/x", 401, "Unauthorized", {}, io.BytesIO(body))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": self.SECRET}, clear=True), \
                mock.patch.object(gh_client, "winreg", None), \
                mock.patch("gh_client.urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(GhError) as ctx:
                gh_client.request("GET", "/repos/o/r")
        message = str(ctx.exception)
        self.assertNotIn(self.SECRET, message)
        self.assertNotIn("Authorization", message)
        self.assertIn("GET /repos/o/r failed: HTTP 401", message)
        self.assertEqual(ctx.exception.status, 401)

    def test_error_message_is_truncated_to_300_characters(self):
        body = json.dumps({"message": "x" * 1000}).encode("utf-8")
        http_error = urllib.error.HTTPError("https://api.github.com/x", 500, "Server Error", {}, io.BytesIO(body))
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": self.SECRET}, clear=True), \
                mock.patch("gh_client.urllib.request.urlopen", side_effect=http_error):
            with self.assertRaises(GhError) as ctx:
                gh_client.request("GET", "/x")
        self.assertEqual(str(ctx.exception), "GET /x failed: HTTP 500 " + "x" * 300)

    def test_success_sends_bearer_token_and_parses_json(self):
        response = mock.MagicMock()
        response.read.return_value = b'{"ok": true}'
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": self.SECRET}, clear=True), \
                mock.patch("gh_client.urllib.request.urlopen", return_value=response) as opener:
            result = gh_client.request("GET", "/repos/o/r")
        self.assertEqual(result, {"ok": True})
        sent = opener.call_args[0][0]
        self.assertEqual(sent.get_header("Authorization"), f"Bearer {self.SECRET}")
        self.assertEqual(sent.get_header("Accept"), "application/vnd.github+json")

    def test_empty_response_returns_none(self):
        response = mock.MagicMock()
        response.read.return_value = b""
        response.__enter__.return_value = response
        with mock.patch.dict(os.environ, {"GITHUB_TOKEN": self.SECRET}, clear=True), \
                mock.patch("gh_client.urllib.request.urlopen", return_value=response):
            self.assertIsNone(gh_client.request("DELETE", "/x"))

    def test_request_all_follows_pages(self):
        pages = [[{}] * 100, [{}] * 5]
        with mock.patch.object(gh_client, "request", side_effect=pages):
            self.assertEqual(len(gh_client.request_all("/x")), 105)

    def test_request_all_reads_keyed_list(self):
        pages = [{"check_runs": [{}] * 100}, {"check_runs": [{}]}]
        with mock.patch.object(gh_client, "request", side_effect=pages):
            self.assertEqual(len(gh_client.request_all("/x", key="check_runs")), 101)

    def test_count_request_changes_only_counts_marker(self):
        comments = [
            {"body": gh_client.REQUEST_CHANGES_MARKER + "\nfix it"},
            {"body": None},
            {"body": "<!-- factory-review:escalate -->"},
        ]
        self.assertEqual(gh_client.count_request_changes(comments), 1)

    def test_marker_only_counts_on_first_line(self):
        comments = [
            {"body": "Summary first\n" + gh_client.REQUEST_CHANGES_MARKER + "\nfix it"},
            {"body": "\n" + gh_client.REQUEST_CHANGES_MARKER},
            {"body": "Quoted: " + gh_client.REQUEST_CHANGES_MARKER},
            {"body": "  " + gh_client.REQUEST_CHANGES_MARKER + "  \r\nfix"},
        ]
        self.assertEqual([gh_client.is_request_changes(c) for c in comments], [False, False, False, True])


class PrStateSummaryTests(unittest.TestCase):
    def test_checks_use_newest_run_per_name(self):
        runs = [
            {"id": 1, "name": "test", "status": "completed", "conclusion": "failure"},
            {"id": 2, "name": "test", "status": "completed", "conclusion": "success"},
            {"id": 3, "name": "apps", "status": "in_progress", "conclusion": None},
        ]
        self.assertEqual(pr_state.summarize_checks(runs), ["apps=in_progress", "test=success"])

    def test_no_checks(self):
        self.assertEqual(pr_state.summarize_checks([]), [])

    def test_newest_status_for_context(self):
        statuses = [
            {"context": "factory/review", "state": "failure", "created_at": "2026-11-09T10:00:00Z", "id": 1},
            {"context": "factory/review", "state": "success", "created_at": "2026-11-09T11:00:00Z", "id": 2},
            {"context": "test", "state": "failure", "created_at": "2026-11-09T12:00:00Z", "id": 3},
        ]
        self.assertEqual(pr_state.newest_status(statuses, "factory/review"), "success")

    def test_status_none_when_absent(self):
        self.assertEqual(pr_state.newest_status([], "factory/review"), "none")
        self.assertEqual(pr_state.newest_status([{"context": "test", "state": "success"}], "factory/review"), "none")


class PrFeedbackTests(unittest.TestCase):
    def test_newest_request_changes_comment_wins(self):
        comments = [
            {"body": "<!-- factory-review:request-changes -->\nold", "created_at": "2026-01-01T00:00:00Z"},
            {"body": "<!-- factory-review:request-changes -->\nnew", "created_at": "2026-01-02T00:00:00Z"},
            {"body": "<!-- factory-review:approve -->", "created_at": "2026-01-03T00:00:00Z"},
        ]
        self.assertTrue(pr_feedback.newest_request_changes(comments)["body"].endswith("new"))

    def test_no_request_changes_comment(self):
        self.assertIsNone(pr_feedback.newest_request_changes([{"body": "hello"}]))

    def test_inline_format_uses_line_or_original_line(self):
        self.assertEqual(pr_feedback.format_inline({"path": "a.py", "line": 12, "body": "fix"}), "a.py:12 - fix")
        self.assertEqual(
            pr_feedback.format_inline({"path": "b.py", "line": None, "original_line": 5, "body": "x"}),
            "b.py:5 - x",
        )


class TempRepoCase(unittest.TestCase):
    """A throwaway git repository. Each test runs inside it and returns to the old directory afterwards."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        old_cwd = os.getcwd()
        self.addCleanup(os.chdir, old_cwd)
        os.chdir(tmp.name)
        self.git("init", "-q")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "Test")
        self.git("config", "commit.gpgsign", "false")
        self.write("outside/a.txt", "a\n")
        self.write("products/x/b.txt", "b\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "initial")
        self.git("switch", "-q", "-c", "work")

    def git(self, *args):
        result = subprocess.run(["git", *args], capture_output=True, text=True, check=True)
        return result.stdout

    def write(self, path, text):
        folder = os.path.dirname(path)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(text)

    def snapshot(self):
        return {
            "branch": self.git("rev-parse", "--abbrev-ref", "HEAD").strip(),
            "head": self.git("rev-parse", "HEAD").strip(),
            "branches": self.git("branch", "--list"),
            "index": self.git("ls-files", "--stage"),
            "staged": self.git("diff", "--cached", "--name-status"),
        }

    def run_publish(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = publish_branch.main(argv)
        return code, out.getvalue(), err.getvalue()


class BareRemoteCase(TempRepoCase):
    """The throwaway repository plus a bare remote named origin. Nothing is pushed unless a test pushes it."""

    def setUp(self):
        super().setUp()
        remote = tempfile.TemporaryDirectory()
        self.addCleanup(remote.cleanup)
        self.remote_dir = remote.name
        subprocess.run(["git", "init", "-q", "--bare", self.remote_dir], capture_output=True, check=True)
        self.git("remote", "add", "origin", self.remote_dir)

    def remote_refs(self):
        """Every ref the bare remote holds, read from the remote itself."""
        result = subprocess.run(
            ["git", "--git-dir", self.remote_dir, "for-each-ref", "--format=%(refname)"],
            capture_output=True,
            text=True,
            check=True,
        )
        return result.stdout.split()

    def remote_ref(self, name):
        result = subprocess.run(
            ["git", "--git-dir", self.remote_dir, "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],
            capture_output=True,
            text=True,
            check=False,
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def commit_locally(self):
        self.write("products/x/c.txt", "local commit\n")
        self.git("add", "products/x/c.txt")
        self.git("commit", "-q", "-m", "local work")

    def commit_outside_scope(self):
        self.write("outside/d.txt", "outside scope\n")
        self.git("add", "outside/d.txt")
        self.git("commit", "-q", "-m", "outside work")


class RemoteWithMainCase(BareRemoteCase):
    """origin already holds the initial commit as main, so origin/main exists locally."""

    def setUp(self):
        super().setUp()
        self.git("push", "-q", "origin", "work:refs/heads/main")


class PublishDryRunTests(RemoteWithMainCase):
    def test_dry_run_changes_no_git_state(self):
        self.write("products/x/b.txt", "changed\n")
        self.write("products/x/new/c.txt", "new\n")
        self.write("outside/a.txt", "unstaged change outside scope\n")
        before = self.snapshot()

        code, out, _ = self.run_publish(
            ["--branch", "feat/dry", "--scope", "products/x", "--message", "m", "--dry-run"]
        )

        self.assertEqual(code, publish_branch.EXIT_OK)
        self.assertIn("  products/x/b.txt", out)
        self.assertIn("  products/x/new/c.txt", out)
        self.assertNotIn("outside/a.txt", out)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(before["branch"], "work")
        self.assertNotIn("feat/dry", self.git("branch", "--list"))

    def test_dry_run_does_not_stage_scope_files(self):
        self.write("products/x/new/c.txt", "new\n")
        code, _, _ = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m", "--dry-run"])
        self.assertEqual(code, publish_branch.EXIT_OK)
        self.assertEqual(self.git("diff", "--cached", "--name-only").strip(), "")

    def test_dry_run_refuses_pre_staged_path_outside_scope(self):
        self.write("outside/a.txt", "staged outside scope\n")
        self.git("add", "outside/a.txt")
        before = self.snapshot()

        code, _, err = self.run_publish(
            ["--branch", "feat/dry", "--scope", "products/x", "--message", "m", "--dry-run"]
        )

        self.assertEqual(code, publish_branch.EXIT_OUTSIDE_SCOPE)
        self.assertIn("outside/a.txt", err)
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_with_nothing_to_publish_exits_ok(self):
        before = self.snapshot()
        code, out, _ = self.run_publish(["--branch", "feat/dry", "--scope", "products/x", "--message", "m", "--dry-run"])
        self.assertEqual(code, publish_branch.EXIT_OK)
        self.assertIn("nothing to publish", out)
        self.assertEqual(self.snapshot(), before)


class PublishOutOfScopeRenameTests(RemoteWithMainCase):
    def test_staged_rename_out_of_scope_is_refused_with_exit_3(self):
        # Move a tracked file from outside the scope into it. Rename detection would hide the source.
        os.makedirs("products/x", exist_ok=True)
        self.git("mv", "outside/a.txt", "products/x/a.txt")
        head_before = self.git("rev-parse", "HEAD").strip()

        code, _, err = self.run_publish(["--branch", "feat/rename", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_OUTSIDE_SCOPE)
        self.assertIn("outside/a.txt", err)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), head_before)
        self.assertEqual(self.git("diff", "--cached", "--name-only").strip(), "")


class RemotePublishTests(RemoteWithMainCase):
    """Nothing staged: publish_branch must push local commits that origin does not have yet."""

    def test_nothing_staged_and_ahead_pushes_local_commits(self):
        self.commit_locally()
        head = self.git("rev-parse", "HEAD").strip()
        self.assertIsNone(self.remote_ref("work"))

        code, out, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_OK, err)
        self.assertIn("pushed 1 unpublished commit(s)", out)
        self.assertEqual(self.remote_ref("work"), head)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), head)

    def test_nothing_staged_and_not_ahead_pushes_nothing(self):
        before = self.snapshot()

        code, out, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_OK, err)
        self.assertIn("nothing to publish", out)
        self.assertIsNone(self.remote_ref("work"))
        self.assertEqual(self.snapshot(), before)

    def test_dry_run_when_ahead_reports_push_and_pushes_nothing(self):
        self.commit_locally()
        before = self.snapshot()

        code, out, err = self.run_publish(
            ["--branch", "work", "--scope", "products/x", "--message", "m", "--dry-run"]
        )

        self.assertEqual(code, publish_branch.EXIT_OK, err)
        self.assertIn("would push 1 commit to origin/work", out)
        self.assertNotIn("nothing to publish", out)
        self.assertIsNone(self.remote_ref("work"))
        self.assertEqual(self.snapshot(), before)

    def test_push_failure_output_does_not_print_the_remote_url(self):
        self.commit_locally()
        missing = self.remote_dir + "-gone"
        self.git("remote", "set-url", "origin", missing)

        code, _, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_GIT)
        self.assertIn("error: push failed", err)
        self.assertNotIn(missing, err)
        self.assertIn("origin", err)


class UnpushedScopeTests(RemoteWithMainCase):
    """Nothing staged, branch ahead of origin: every unpushed commit must sit inside the scopes before a push."""

    def test_out_of_scope_unpushed_commit_is_refused_and_nothing_is_pushed(self):
        self.commit_locally()
        self.commit_outside_scope()
        before = self.snapshot()

        code, out, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_OUTSIDE_SCOPE, err)
        self.assertIn("outside/d.txt", err)
        self.assertNotIn("pushed", out)
        self.assertIsNone(self.remote_ref("work"))
        self.assertEqual(self.snapshot(), before)

    def test_out_of_scope_unpushed_commit_dry_run_is_refused_and_nothing_is_pushed(self):
        self.commit_outside_scope()
        before = self.snapshot()

        code, out, err = self.run_publish(
            ["--branch", "work", "--scope", "products/x", "--message", "m", "--dry-run"]
        )

        self.assertEqual(code, publish_branch.EXIT_OUTSIDE_SCOPE, err)
        self.assertIn("outside/d.txt", err)
        self.assertNotIn("would push", out)
        self.assertIsNone(self.remote_ref("work"))
        self.assertEqual(self.snapshot(), before)

    def test_out_of_scope_file_added_then_removed_is_still_refused(self):
        self.commit_outside_scope()
        self.git("rm", "-q", "outside/d.txt")
        self.git("commit", "-q", "-m", "remove again")
        self.commit_locally()

        code, _, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_OUTSIDE_SCOPE, err)
        self.assertIn("outside/d.txt", err)
        self.assertIsNone(self.remote_ref("work"))

    def test_staged_in_scope_change_with_out_of_scope_unpushed_commit_is_refused(self):
        self.commit_outside_scope()
        self.write("products/x/b.txt", "staged change\n")
        self.git("add", "products/x/b.txt")
        head = self.git("rev-parse", "HEAD").strip()

        code, _, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_OUTSIDE_SCOPE, err)
        self.assertEqual(self.git("rev-parse", "HEAD").strip(), head)
        self.assertIsNone(self.remote_ref("work"))
        self.assertIn("products/x/b.txt", self.git("diff", "--cached", "--name-only"))

    def test_no_scope_is_refused_with_exit_2_and_nothing_is_pushed(self):
        self.commit_locally()
        with self.assertRaises(SystemExit) as caught:
            self.run_publish(["--branch", "work", "--message", "m"])
        self.assertEqual(caught.exception.code, publish_branch.EXIT_REFUSED)
        self.assertIsNone(self.remote_ref("work"))


class NoRemoteBaseTests(BareRemoteCase):
    """origin exists but holds no refs, so neither origin/work nor origin/main exists locally."""

    def test_missing_base_with_unpushed_commit_exits_1_without_success_message(self):
        self.commit_locally()
        before = self.snapshot()

        code, out, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_GIT)
        self.assertIn(publish_branch.NO_BASE_MESSAGE, err)
        self.assertNotIn("pushed", out)
        self.assertNotIn("nothing to publish", out)
        self.assertEqual(self.remote_refs(), [])
        self.assertEqual(self.snapshot(), before)

    def test_missing_base_with_nothing_local_still_exits_1_not_nothing_to_publish(self):
        code, out, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_GIT)
        self.assertIn(publish_branch.NO_BASE_MESSAGE, err)
        self.assertNotIn("nothing to publish", out)
        self.assertEqual(self.remote_refs(), [])

    def test_missing_base_dry_run_exits_1_and_changes_nothing(self):
        self.commit_locally()
        before = self.snapshot()

        code, out, err = self.run_publish(
            ["--branch", "work", "--scope", "products/x", "--message", "m", "--dry-run"]
        )

        self.assertEqual(code, publish_branch.EXIT_GIT)
        self.assertIn(publish_branch.NO_BASE_MESSAGE, err)
        self.assertNotIn("would push", out)
        self.assertNotIn("nothing to publish", out)
        self.assertEqual(self.remote_refs(), [])
        self.assertEqual(self.snapshot(), before)

    def test_missing_base_dry_run_with_nothing_local_exits_1(self):
        code, out, err = self.run_publish(
            ["--branch", "work", "--scope", "products/x", "--message", "m", "--dry-run"]
        )

        self.assertEqual(code, publish_branch.EXIT_GIT)
        self.assertIn(publish_branch.NO_BASE_MESSAGE, err)
        self.assertNotIn("nothing to publish", out)

    def test_missing_base_with_staged_path_leaves_index_and_head_alone(self):
        self.write("products/x/c.txt", "staged\n")
        self.git("add", "products/x/c.txt")
        before = self.snapshot()

        code, _, err = self.run_publish(["--branch", "work", "--scope", "products/x", "--message", "m"])

        self.assertEqual(code, publish_branch.EXIT_GIT)
        self.assertIn(publish_branch.NO_BASE_MESSAGE, err)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.remote_refs(), [])


class RedactionTests(unittest.TestCase):
    def test_redact_prints_origin_for_its_url_and_strips_credentials_from_others(self):
        urls = ["https://user:secret@example.invalid/repo.git"]
        text = (
            "To https://user:secret@example.invalid/repo.git\n"
            " ! [rejected] work -> work\n"
            "fatal: see https://other:pw@example.org/x for details"
        )

        out = publish_branch._redact(text, urls)

        self.assertIn("To origin", out)
        self.assertNotIn("secret", out)
        self.assertNotIn("pw@", out)
        self.assertIn("https://example.org/x", out)


class ReviewAutoMergeGuardTests(unittest.TestCase):
    def test_base_without_factory_review_does_not_require_status(self):
        protection = {"required_status_checks": {"contexts": ["test"]}}
        with mock.patch.object(review_pr, "request", return_value=protection):
            self.assertFalse(review_pr.base_requires_status("o", "r", "main"))

    def test_base_with_factory_review_requires_status(self):
        protection = {"required_status_checks": {"contexts": ["test", "factory/review"]}}
        with mock.patch.object(review_pr, "request", return_value=protection):
            self.assertTrue(review_pr.base_requires_status("o", "r", "main"))

    def test_http_404_on_protection_read_means_no_protection(self):
        not_found = GhError("GET /repos/o/r/branches/main/protection failed: HTTP 404 Branch not protected", status=404)
        with mock.patch.object(review_pr, "request", side_effect=not_found):
            self.assertFalse(review_pr.base_requires_status("o", "r", "main"))

    def test_other_protection_read_errors_are_not_hidden(self):
        server_error = GhError("GET /x failed: HTTP 500 boom", status=500)
        with mock.patch.object(review_pr, "request", side_effect=server_error):
            with self.assertRaises(GhError):
                review_pr.base_requires_status("o", "r", "main")

    def test_base_branch_name_with_slash_keeps_slash_in_path(self):
        with mock.patch.object(review_pr, "request", return_value={}) as request:
            review_pr.base_requires_status("o", "r", "release/1.0")
        paths = [call[0][1] for call in request.call_args_list]
        self.assertEqual(paths, ["/repos/o/r/branches/release/1.0/protection", "/repos/o/r/rules/branches/release/1.0"])

    def test_base_branch_name_with_query_and_fragment_chars_is_percent_encoded(self):
        with mock.patch.object(review_pr, "request", return_value={}) as request:
            review_pr.base_requires_status("o", "r", "feat?x#y")
        paths = [call[0][1] for call in request.call_args_list]
        self.assertEqual(paths, ["/repos/o/r/branches/feat%3Fx%23y/protection", "/repos/o/r/rules/branches/feat%3Fx%23y"])


def _ruleset_rule(context, rule_type="required_status_checks"):
    return {"type": rule_type, "parameters": {"required_status_checks": [{"context": context}]}}


class RulesetGuardTests(unittest.TestCase):
    def test_rules_with_required_factory_review_check_require_status(self):
        rules = [{"type": "deletion"}, _ruleset_rule("test"), _ruleset_rule(review_pr.STATUS_CONTEXT)]
        self.assertTrue(review_pr.rules_require_status(rules, review_pr.STATUS_CONTEXT))

    def test_rules_without_required_factory_review_check_do_not_require_status(self):
        rules = [_ruleset_rule("test")]
        self.assertFalse(review_pr.rules_require_status(rules, review_pr.STATUS_CONTEXT))

    def test_rule_of_another_type_with_same_context_does_not_require_status(self):
        rules = [_ruleset_rule(review_pr.STATUS_CONTEXT, rule_type="pull_request")]
        self.assertFalse(review_pr.rules_require_status(rules, review_pr.STATUS_CONTEXT))

    def test_empty_rules_list_does_not_require_status(self):
        self.assertFalse(review_pr.rules_require_status([], review_pr.STATUS_CONTEXT))

    def test_similar_context_name_does_not_match(self):
        rules = [_ruleset_rule("factory/reviewer"), _ruleset_rule("Factory/Review")]
        self.assertFalse(review_pr.rules_require_status(rules, review_pr.STATUS_CONTEXT))

    def test_missing_or_malformed_rules_do_not_require_status(self):
        self.assertFalse(review_pr.rules_require_status(None, review_pr.STATUS_CONTEXT))
        self.assertFalse(review_pr.rules_require_status({"type": "required_status_checks"}, review_pr.STATUS_CONTEXT))
        malformed = [{"type": "required_status_checks", "parameters": {"required_status_checks": "factory/review"}},
                     {"type": "required_status_checks"}, "factory/review"]
        self.assertFalse(review_pr.rules_require_status(malformed, review_pr.STATUS_CONTEXT))

    def _decide(self, protection=None, protection_404=False, rules=None, rules_404=False):
        def fake_request(method, path, body=None):
            if path.endswith("/protection"):
                if protection_404:
                    raise GhError("GET protection failed: HTTP 404 Branch not protected", status=404)
                return protection
            if rules_404:
                raise GhError("GET rules failed: HTTP 404 Not Found", status=404)
            return rules if rules is not None else []

        with mock.patch.object(review_pr, "request", side_effect=fake_request):
            return review_pr.base_requires_status("o", "r", "main")

    def test_rulesets_with_factory_review_give_true(self):
        self.assertTrue(self._decide(protection_404=True, rules=[_ruleset_rule(review_pr.STATUS_CONTEXT)]))

    def test_classic_protection_only_gives_true(self):
        self.assertTrue(self._decide(protection=REQUIRES_STATUS, rules=[]))

    def test_neither_source_gives_false(self):
        self.assertFalse(self._decide(protection=NO_STATUS, rules=[_ruleset_rule("test")]))
        self.assertFalse(self._decide(protection_404=True, rules=[]))

    def test_404_on_rules_endpoint_with_classic_present_gives_true(self):
        self.assertTrue(self._decide(protection=REQUIRES_STATUS, rules_404=True))

    def test_404_on_protection_with_rules_present_gives_true(self):
        self.assertTrue(self._decide(protection_404=True, rules=[_ruleset_rule(review_pr.STATUS_CONTEXT)]))

    def test_non_404_error_on_rules_endpoint_is_not_hidden(self):
        def fake_request(method, path, body=None):
            if path.endswith("/protection"):
                return NO_STATUS
            raise GhError("GET rules failed: HTTP 500 boom", status=500)

        with mock.patch.object(review_pr, "request", side_effect=fake_request):
            with self.assertRaises(GhError):
                review_pr.base_requires_status("o", "r", "main")

    def test_enable_auto_merge_sends_squash_mutation_for_pr_node_id(self):
        def fake_graphql(query, variables=None):
            if query == review_pr.PR_ID_QUERY:
                self.assertEqual(variables, {"owner": "o", "name": "r", "number": 8})
                return {"repository": {"pullRequest": {"id": "PR_node_8"}}}
            self.assertEqual(query, review_pr.AUTO_MERGE_MUTATION)
            self.assertEqual(variables, {"id": "PR_node_8"})
            return {"enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": {"enabledAt": "t"}}}}

        with mock.patch.object(review_pr, "graphql", side_effect=fake_graphql) as graphql:
            enabled = review_pr.enable_auto_merge("o", "r", 8)
        self.assertEqual(enabled, {"enabledAt": "t"})
        self.assertEqual(graphql.call_count, 2)
        self.assertIn("mergeMethod: SQUASH", review_pr.AUTO_MERGE_MUTATION)

    def test_enable_auto_merge_refuses_missing_pull_request(self):
        with mock.patch.object(review_pr, "graphql", return_value={"repository": {"pullRequest": None}}):
            with self.assertRaises(GhError):
                review_pr.enable_auto_merge("o", "r", 99)

    def test_enable_auto_merge_returns_none_when_github_reports_null(self):
        def fake_graphql(query, variables=None):
            if query == review_pr.PR_ID_QUERY:
                return {"repository": {"pullRequest": {"id": "PR_node_8"}}}
            return {"enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": None}}}

        with mock.patch.object(review_pr, "graphql", side_effect=fake_graphql):
            self.assertIsNone(review_pr.enable_auto_merge("o", "r", 8))


PR_OPEN = {
    "state": "open",
    "head": {"sha": "abc123"},
    "base": {"ref": "main"},
    "html_url": "https://github.com/o/r/pull/8",
}
REQUIRES_STATUS = {"required_status_checks": {"contexts": ["factory/review"]}}
NO_STATUS = {"required_status_checks": {"contexts": ["test"]}}


class ReviewExecutionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.body_path = os.path.join(tmp.name, "review.md")
        with open(self.body_path, "w", encoding="utf-8") as handle:
            handle.write("Review body\n")

    def _run(self, decision, protection=None, protection_missing=False, comments=(), pr=PR_OPEN, extra=(),
             auto_merge_request={"enabledAt": "t"}, rules=(), rules_missing=False):
        calls = []

        def fake_request(method, path, body=None):
            calls.append((method, path, body))
            if method == "GET" and path.endswith("/protection"):
                if protection_missing:
                    raise GhError("GET protection failed: HTTP 404 Branch not protected", status=404)
                return protection
            if method == "GET" and "/rules/branches/" in path:
                if rules_missing:
                    raise GhError("GET rules failed: HTTP 404 Not Found", status=404)
                return list(rules)
            if method == "GET" and "/pulls/" in path:
                return pr
            return {"id": 1}

        def fake_graphql(query, variables=None):
            calls.append(("GRAPHQL", query, variables))
            if query == review_pr.PR_ID_QUERY:
                return {"repository": {"pullRequest": {"id": "PR_node_8"}}}
            return {"enablePullRequestAutoMerge": {"pullRequest": {"autoMergeRequest": auto_merge_request}}}

        argv = ["--pr", "8", "--decision", decision, "--body-file", self.body_path, *extra]
        out = io.StringIO()
        err = io.StringIO()
        with mock.patch.object(review_pr, "repo", return_value=("o", "r")), \
                mock.patch.object(review_pr, "request", side_effect=fake_request), \
                mock.patch.object(review_pr, "request_all", return_value=list(comments)), \
                mock.patch.object(review_pr, "graphql", side_effect=fake_graphql), \
                contextlib.redirect_stdout(out), \
                contextlib.redirect_stderr(err):
            code = review_pr.main(argv)
        self.last_err = err.getvalue()
        return code, calls, out.getvalue()

    @staticmethod
    def _posts(calls):
        return [(path, body) for method, path, body in calls if method == "POST" and path != "/graphql"]

    @staticmethod
    def _graphql_calls(calls):
        return [call for call in calls if call[0] == "GRAPHQL"]

    def test_approve_with_factory_review_protection_sets_status_then_comment_then_automerge(self):
        code, calls, _ = self._run("approve", protection=REQUIRES_STATUS)
        self.assertEqual(code, 0)
        posts = self._posts(calls)
        self.assertEqual([path for path, _ in posts], ["/repos/o/r/statuses/abc123", "/repos/o/r/issues/8/comments"])
        status_body = posts[0][1]
        self.assertEqual(status_body["state"], "success")
        self.assertEqual(status_body["context"], "factory/review")
        comment_body = posts[1][1]["body"]
        self.assertEqual(comment_body.splitlines()[0], "<!-- factory-review:approve -->")
        graphql = self._graphql_calls(calls)
        self.assertEqual(len(graphql), 2)
        self.assertEqual(graphql[1][1], review_pr.AUTO_MERGE_MUTATION)
        self.assertEqual(graphql[1][2], {"id": "PR_node_8"})

    def test_approve_without_factory_review_protection_does_not_enable_automerge(self):
        code, calls, out = self._run("approve", protection=NO_STATUS)
        self.assertEqual(code, 0)
        self.assertEqual(self._graphql_calls(calls), [])
        self.assertIn("automerge:skipped-no-protection", out)
        self.assertEqual(len(self._posts(calls)), 2)

    def test_approve_with_no_protection_404_does_not_enable_automerge(self):
        code, calls, _ = self._run("approve", protection_missing=True)
        self.assertEqual(code, 0)
        self.assertEqual(self._graphql_calls(calls), [])
        posts = self._posts(calls)
        self.assertEqual(posts[0][1]["state"], "success")
        self.assertEqual(posts[1][1]["body"].splitlines()[0], "<!-- factory-review:approve -->")

    def test_escalate_path_after_limit_posts_escalation_and_failure_status(self):
        prior = [{"body": review_pr.MARKERS["request-changes"] + "\nfix"} for _ in range(3)]
        code, calls, _ = self._run("request-changes", protection=REQUIRES_STATUS, comments=prior)
        self.assertEqual(code, 0)
        posts = self._posts(calls)
        self.assertEqual(posts[0][0], "/repos/o/r/statuses/abc123")
        self.assertEqual(posts[0][1]["state"], "failure")
        self.assertEqual(posts[0][1]["description"], "Rework limit reached; human decision needed")
        comment_body = posts[1][1]["body"]
        self.assertEqual(comment_body.splitlines()[0], "<!-- factory-review:escalate -->")
        self.assertIn("A human must decide", comment_body)
        self.assertEqual(self._graphql_calls(calls), [])

    def test_request_changes_below_limit_posts_round_status(self):
        prior = [{"body": review_pr.MARKERS["request-changes"] + "\nfix"}]
        code, calls, _ = self._run("request-changes", protection=REQUIRES_STATUS, comments=prior)
        self.assertEqual(code, 0)
        posts = self._posts(calls)
        self.assertEqual(posts[0][1]["description"], "Changes requested (round 2 of 3)")
        self.assertEqual(posts[1][1]["body"].splitlines()[0], "<!-- factory-review:request-changes -->")
        self.assertEqual(self._graphql_calls(calls), [])

    def test_marker_not_on_first_line_does_not_count_toward_limit(self):
        prior = [{"body": "Notes first\n" + review_pr.MARKERS["request-changes"]} for _ in range(3)]
        code, calls, _ = self._run("request-changes", protection=NO_STATUS, comments=prior)
        self.assertEqual(code, 0)
        self.assertEqual(self._posts(calls)[1][1]["body"].splitlines()[0], "<!-- factory-review:request-changes -->")

    def test_approve_with_null_automerge_response_reports_not_enabled_and_fails(self):
        code, calls, out = self._run("approve", protection=REQUIRES_STATUS, auto_merge_request=None)
        self.assertEqual(code, 1)
        self.assertIn("  automerge:not-enabled", out)
        self.assertNotIn("  automerge:enable", out)
        self.assertIn("did not enable auto-merge on #8", self.last_err)
        self.assertEqual(len(self._graphql_calls(calls)), 2)
        posts = self._posts(calls)
        self.assertEqual(posts[0][1]["state"], "success")
        self.assertEqual(posts[1][1]["body"].splitlines()[0], "<!-- factory-review:approve -->")

    def test_approve_with_ruleset_factory_review_enables_automerge_without_classic_protection(self):
        rules = [_ruleset_rule(review_pr.STATUS_CONTEXT)]
        code, calls, out = self._run("approve", protection_missing=True, rules=rules)
        self.assertEqual(code, 0)
        self.assertIn("  automerge:enable", out)
        self.assertEqual(len(self._graphql_calls(calls)), 2)

    def test_approve_with_no_rules_and_no_protection_skips_automerge(self):
        code, calls, out = self._run("approve", protection_missing=True, rules_missing=True)
        self.assertEqual(code, 0)
        self.assertIn("automerge:skipped-no-protection", out)
        self.assertEqual(self._graphql_calls(calls), [])

    def test_approve_with_enabled_automerge_reports_enable_and_succeeds(self):
        code, _, out = self._run("approve", protection=REQUIRES_STATUS)
        self.assertEqual(code, 0)
        self.assertIn("  automerge:enable", out)
        self.assertNotIn("automerge:not-enabled", out)
        self.assertEqual(self.last_err, "")

    def test_approve_at_limit_escalates_and_never_enables_automerge(self):
        prior = [{"body": review_pr.MARKERS["request-changes"] + "\nfix"} for _ in range(3)]
        code, calls, out = self._run("approve", protection=REQUIRES_STATUS, comments=prior)
        self.assertEqual(code, 0)
        self.assertEqual(self._graphql_calls(calls), [])
        self.assertIn("  comment:escalate", out)
        self.assertNotIn("automerge", out)
        posts = self._posts(calls)
        self.assertEqual(posts[0][1]["state"], "failure")
        self.assertEqual(posts[1][1]["body"].splitlines()[0], "<!-- factory-review:escalate -->")

    def test_dry_run_makes_no_writes(self):
        code, calls, out = self._run("approve", protection=REQUIRES_STATUS, extra=["--dry-run"])
        self.assertEqual(code, 0)
        self.assertEqual(self._posts(calls), [])
        self.assertEqual(self._graphql_calls(calls), [])
        self.assertIn("dry run: no writes made", out)

    def test_closed_pull_request_is_refused_without_writes(self):
        closed = dict(PR_OPEN, state="closed")
        code, calls, _ = self._run("approve", protection=REQUIRES_STATUS, pr=closed)
        self.assertEqual(code, 2)
        self.assertEqual(self._posts(calls), [])


if __name__ == "__main__":
    unittest.main()
