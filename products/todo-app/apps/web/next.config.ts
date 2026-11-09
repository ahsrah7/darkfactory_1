import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Tailwind CSS v4 is compiled through its Turbopack loader.
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
