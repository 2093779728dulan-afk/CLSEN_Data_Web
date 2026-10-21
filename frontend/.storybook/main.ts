import type { StorybookConfig } from "@storybook/react-vite";

process.env.VITE_PRODUCT_ANALYTICS_SOURCE ??= "legacy_parser";

const config: StorybookConfig = {
  addons: ["@storybook/addon-a11y"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  stories: ["../src/**/*.stories.@(js|jsx|mjs|ts|tsx)"],
  // Serve the locked package directly. Vite's /@fs URLs can point into a
  // different worktree when existing pnpm dependencies are junctions.
  staticDirs: [{
    from: "../node_modules/@fontsource-variable/noto-sans-sc",
    to: "/storybook-fonts/noto-sans-sc",
  }],
};

export default config;
