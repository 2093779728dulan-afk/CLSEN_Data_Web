import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";

import { App } from "./app/App";
import "./design-system/tokens.css";
import "./design-system/primitives.css";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
  throw new Error("Missing #root mount element");
}

createRoot(root).render(
  <StrictMode>
    <BrowserRouter>
      <App />
    </BrowserRouter>
  </StrictMode>,
);
