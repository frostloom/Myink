import vue from 'eslint-plugin-vue'
import ts from 'typescript-eslint'

export default [
  ...vue.configs['flat/recommended'],
  { files: ['vue/src/**/*.ts'], languageOptions: { parser: ts.parser } },
  {
    files: ['vue/src/**/*.vue', 'vue/src/**/*.ts'],
    languageOptions: { parserOptions: { parser: ts.parser, ecmaVersion: 'latest', sourceType: 'module' } },
    rules: {
      'vue/html-self-closing': ['error', { html: { void: 'always', normal: 'always', component: 'always' } }],
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/html-indent': 'off',
    },
  },
]
