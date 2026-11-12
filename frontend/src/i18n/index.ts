/** i18next setup: English and Hindi from reviewed JSON files (no run-time machine translation). */
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import en from "./en.json";
import hi from "./hi.json";

const KEY = "duly.lang";

function savedLanguage(): string {
  try {
    return localStorage.getItem(KEY) ?? "en";
  } catch {
    return "en";
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, hi: { translation: hi } },
  lng: savedLanguage(),
  fallbackLng: "en",
  interpolation: { escapeValue: false }, // React already escapes
});

export function setLanguage(lng: "en" | "hi"): void {
  void i18n.changeLanguage(lng);
  document.documentElement.lang = lng;
  try {
    localStorage.setItem(KEY, lng);
  } catch {
    /* storage unavailable: language lasts for this session */
  }
}

export default i18n;
