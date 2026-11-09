"""Unit tests for the factory PR scripts. No network access."""

import io
import json
import os
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

    def test_approve_never_requests_changes_or_escalates(self):
        for prior in range(6):
            for requires in (True, False):
                with self.subTest(prior=prior, requires=requires):
                    actions = review_pr.plan_review("approve", prior, requires, 3)
                    self.assertIn("comment:approve", actions)
                    self.assertNotIn("comment:request-changes", actions)
                    self.assertNotIn("comment:escalate", actions)
                    self.assertNotIn("status:failure", actions)

    def test_request_changes_never_enables_automerge(self):
        for prior in range(5):
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


if __name__ == "__main__":
    unittest.main()
