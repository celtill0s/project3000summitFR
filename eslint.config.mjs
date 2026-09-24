// Lint du frontend (modules ES dans static/js/, sans bundler). Lancé par la CI :
//   npm install --no-save eslint@9 globals && npx eslint
import globals from "globals";

export default [
  { ignores: ["static/vendor/**"] }, // bibliothèques tierces copiées telles quelles
  {
    files: ["static/js/**/*.js"],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: "module",
      globals: { ...globals.browser, L: "readonly" }, // L : Leaflet, chargé en <script> classique
    },
    rules: {
      "no-undef": "error",
      "no-unused-vars": ["error", { args: "none" }],
    },
  },
];
