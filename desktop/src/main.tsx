import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { SCALE_KEY, THEME_KEY } from "./api";
import { ToastProvider } from "./ui";
import "./styles.css";

document.documentElement.dataset.theme = localStorage.getItem(THEME_KEY) || "dark";
document.documentElement.style.setProperty(
  "--scale",
  String(Number(localStorage.getItem(SCALE_KEY) || 1)),
);

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <ToastProvider>
      <App />
    </ToastProvider>
  </React.StrictMode>,
);
