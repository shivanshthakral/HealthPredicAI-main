import React from "react";
import { createRoot } from "react-dom/client";
import { AuthProvider } from "./context/AuthContext";
import { ThemeProvider } from "./context/ThemeContext";
import App from "./App";
import "./i18n";
import "./index.css";
import "./styles/design-tokens.css";
import "./styles/healthpredict.css";

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <App />
      </AuthProvider>
    </ThemeProvider>
  </React.StrictMode>
);
