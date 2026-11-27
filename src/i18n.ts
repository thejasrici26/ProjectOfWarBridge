import { useEffect, useState } from 'react'
import english from './locales/en.json' with { type: 'json' }
import hindi from './locales/hi.json' with { type: 'json' }
import arabic from './locales/ar.json' with { type: 'json' }

export type Language = 'en' | 'hi' | 'ar'
type Dictionary = Record<string, string>
type DocumentLanguageTarget = Pick<HTMLElement, 'lang' | 'dir'>

const dictionaries: Record<Language, Dictionary> = { en: english, hi: hindi, ar: arabic }
export const availableLanguages: Language[] = ['en', 'hi', 'ar']

function localeTag(language: Language) {
  if (language === 'ar') return 'ar-u-nu-arab'
  if (language === 'hi') return 'hi-u-nu-deva'
  return language
}

export function directionForLanguage(language: Language): 'ltr' | 'rtl' {
  return language === 'ar' ? 'rtl' : 'ltr'
}

export function applyDocumentLanguage(language: Language, target: DocumentLanguageTarget) {
  target.lang = language
  target.dir = directionForLanguage(language)
}

export function translate(language: Language, key: string, values: Record<string, string | number> = {}) {
  let message = dictionaries[language][key] ?? dictionaries.en[key] ?? key
  for (const [name, value] of Object.entries(values)) {
    message = message.split(`{${name}}`).join(String(value))
  }
  return message
}

export function formatNumber(language: Language, value: number, options?: Intl.NumberFormatOptions) {
  return new Intl.NumberFormat(localeTag(language), options).format(value)
}

export function formatDate(language: Language, value: string | Date, includeTime = false) {
  const date = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(date.getTime())) return String(value)
  return new Intl.DateTimeFormat(localeTag(language), includeTime
    ? { dateStyle: 'medium', timeStyle: 'short' }
    : { dateStyle: 'medium' }).format(date)
}

export function formatPhone(language: Language, value: string) {
  const digits = new Intl.NumberFormat(localeTag(language), { useGrouping: false })
  return value.replace(/[0-9]/g, digit => digits.format(Number(digit)))
}

function initialLanguage(): Language {
  if (typeof window === 'undefined') return 'en'
  const saved = window.localStorage.getItem('warbridge-language')
  if (saved === 'en' || saved === 'hi' || saved === 'ar') return saved
  const browserLanguage = window.navigator.language.split('-')[0]
  return browserLanguage === 'hi' || browserLanguage === 'ar' ? browserLanguage : 'en'
}

export function useI18n() {
  const [language, updateLanguage] = useState<Language>(initialLanguage)

  useEffect(() => {
    applyDocumentLanguage(language, document.documentElement)
    document.title = translate(language, 'WarBridge')
    window.localStorage.setItem('warbridge-language', language)
  }, [language])

  return {
    language,
    setLanguage: updateLanguage,
    t: (key: string, values?: Record<string, string | number>) => translate(language, key, values),
    formatNumber: (value: number, options?: Intl.NumberFormatOptions) => formatNumber(language, value, options),
    formatDate: (value: string | Date, includeTime = false) => formatDate(language, value, includeTime),
    formatPhone: (value: string) => formatPhone(language, value),
  }
}
