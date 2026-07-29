/**
 * ESLint 8 config (.eslintrc format — the installed major still uses it).
 *
 * The `lint` script has existed since the project was scaffolded but had no
 * config to read, so `npm run lint` failed outright and CI never called it.
 */
module.exports = {
  root: true,
  env: { browser: true, es2022: true },
  parserOptions: {
    ecmaVersion: 'latest',
    sourceType: 'module',
    ecmaFeatures: { jsx: true },
  },
  settings: { react: { version: 'detect' } },
  extends: [
    'eslint:recommended',
    'plugin:react/recommended',
    'plugin:react/jsx-runtime',
    'plugin:react-hooks/recommended',
  ],
  plugins: ['react-refresh'],
  rules: {
    // The dependency arrays on the feed's load/useEffect pair are load-bearing:
    // getting them wrong silently stops refetching when a filter changes.
    'react-hooks/exhaustive-deps': 'error',
    // This codebase does not use runtime prop validation anywhere. Turning the
    // rule on would mean adding the prop-types package and declaring shapes for
    // props that already come from a typed API response — checking in the wrong
    // place. If prop safety becomes worth enforcing, TypeScript is the move.
    'react/prop-types': 'off',
    'react-refresh/only-export-components': ['warn', { allowConstantExport: true }],
    'no-unused-vars': ['error', { argsIgnorePattern: '^_' }],
  },
}
