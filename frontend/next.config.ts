import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Pin the workspace root to this app so a stray package-lock.json further up
  // the tree doesn't get picked as the Turbopack root.
  turbopack: {
    root: __dirname,
  },
};

export default nextConfig;
