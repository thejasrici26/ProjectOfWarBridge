import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createRequire } from 'node:module'
import { fileURLToPath } from 'node:url'
import test from 'node:test'
import {
  applyDocumentLanguage,
  directionForLanguage,
  formatDate,
  formatNumber,
  formatPhone,
  translate,
} from '../src/i18n.ts'
import english from '../src/locales/en.json' with { type: 'json' }

const require = createRequire(import.meta.url)
const ts = require('typescript')
const appPath = fileURLToPath(new URL('../src/App.tsx', import.meta.url))
const appSource = readFileSync(appPath, 'utf8')
const appFile = ts.createSourceFile(appPath, appSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX)

test('all JSX text and visible text attributes use translations', () => {
  const missingText = []
  function visit(node) {
    if (ts.isJsxText(node) && node.text.trim()) missingText.push(node.text.trim())
    if (
      ts.isJsxAttribute(node)
      && ['aria-label', 'placeholder', 'title'].includes(node.name.getText(appFile))
      && node.initializer
      && ts.isStringLiteral(node.initializer)
    ) missingText.push(node.initializer.text)
    ts.forEachChild(node, visit)
  }
  visit(appFile)
  assert.deepEqual(missingText, [])
})

test('every literal translation key used by the app exists in English', () => {
  const missingKeys = []
  function visit(node) {
    if (
      ts.isCallExpression(node)
      && ts.isIdentifier(node.expression)
      && node.expression.text === 't'
      && node.arguments.length
      && ts.isStringLiteral(node.arguments[0])
      && !(node.arguments[0].text in english)
    ) missingKeys.push(node.arguments[0].text)
    ts.forEachChild(node, visit)
  }
  visit(appFile)
  assert.deepEqual(missingKeys, [])
  assert.ok(Object.keys(english).length > 0)
})

test('Arabic selects RTL and applies its document language', () => {
  assert.equal(directionForLanguage('ar'), 'rtl')
  assert.equal(directionForLanguage('hi'), 'ltr')
  const documentElement = { lang: '', dir: '' }
  applyDocumentLanguage('ar', documentElement)
  assert.deepEqual(documentElement, { lang: 'ar', dir: 'rtl' })
})

test('missing Hindi and Arabic translations fall back to English', () => {
  const key = 'A bridge to a safer tomorrow'
  assert.equal(translate('hi', key), english[key])
  assert.equal(translate('ar', key), english[key])
})

test('locale formatting handles dates, numbers, and phone digits', () => {
  assert.notEqual(formatNumber('hi', 12345678), '12,345,678')
  assert.notEqual(formatDate('ar', '2026-01-02T03:04:00Z'), formatDate('en', '2026-01-02T03:04:00Z'))
  assert.notEqual(formatPhone('ar', '112'), '112')
})
