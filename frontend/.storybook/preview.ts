import type { Preview } from "@storybook/react-vite";

import "@fontsource-variable/noto-sans-sc";
import "../src/design-system/tokens.css";
import "../src/design-system/primitives.css";
import "./preview.css";

const preview: Preview = {
  initialGlobals: {
    a11y: {
      manual: true,
    },
  },
  parameters: {
    a11y: {
      test: "todo",
    },
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
    layout: "padded",
  },
};

export default preview;
