import type { StorybookConfig } from "@storybook/react-vite";

process.env.VITE_PRODUCT_ANALYTICS_SOURCE ??= "legacy_parser";

const config: StorybookConfig = {
  addons: ["@storybook/addon-a11y"],
  framework: {
    name: "@storybook/react-vite",
    options: {},
  },
  stories: ["../src/**/*.stories.@(js|jsx|mjs|ts|tsx)"],
};

export default config;
