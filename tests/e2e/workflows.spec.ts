import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

let sequence = 0

function testPassword() {
  const password = process.env.WARBRIDGE_E2E_USER_PASSWORD
  if (!password) throw new Error('Playwright did not configure the ephemeral E2E user password.')
  return password
}

function uniqueName(prefix: string) {
  sequence += 1
  return `${prefix} E2E ${Date.now()} ${sequence}`
}

function uniqueEmail(name: string) {
  return `${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}@example.test`
}

async function register(page: Page, hub: string, roleName: string) {
  const name = uniqueName(roleName)
  const email = uniqueEmail(name)
  await page.getByRole('button', { name: hub, exact: true }).click()
  await page.getByRole('button', { name: 'Create an account' }).click()
  await page.getByLabel(roleName === 'NGO' ? 'NGO name or email' : roleName === 'Host' ? 'Host name or email' : 'Name or email').fill(name)
  await page.getByLabel('Contact email').fill(email)
  await page.getByLabel('Password').fill(testPassword())
  await page.getByRole('button', { name: 'Create account' }).click()
  await expect(page.getByRole('heading', { name: roleName === 'NGO' ? 'NGO Dashboard' : roleName === 'Host' ? 'Host Dashboard' : 'Welcome back!' })).toBeVisible()
  return { name, email }
}

async function signOut(page: Page, name: string) {
  await page.getByRole('button', { name: new RegExp(name) }).click()
  await page.getByRole('button', { name: 'Sign out' }).click()
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeVisible()
}

async function signIn(page: Page, hub: string, roleName: string, email: string, expectedHeading: string) {
  await page.getByRole('button', { name: hub, exact: true }).click()
  await page.getByLabel(roleName === 'NGO' ? 'NGO name or email' : roleName === 'Host' ? 'Host name or email' : roleName === 'Administrator' ? 'Administrator username or email' : 'Name or email').fill(email)
  await page.getByLabel('Password').fill(roleName === 'Administrator' ? process.env.WARBRIDGE_E2E_ADMIN_PASSWORD! : testPassword())
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: expectedHeading })).toBeVisible()
}

async function approvePartner(page: Page, partnerName: string) {
  await page.getByRole('button', { name: 'Trust & Safety', exact: true }).click()
  const email = process.env.WARBRIDGE_E2E_ADMIN_EMAIL
  const adminPassword = process.env.WARBRIDGE_E2E_ADMIN_PASSWORD
  if (!email || !adminPassword) throw new Error('Playwright did not configure the ephemeral E2E administrator.')
  await page.getByLabel('Administrator username or email').fill(email)
  await page.getByLabel('Password').fill(adminPassword)
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Platform Analytics' })).toBeVisible()

  const verificationRow = page.locator('.verification-row').filter({ hasText: partnerName })
  await expect(verificationRow).toBeVisible()
  await verificationRow.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(verificationRow).toHaveCount(0)
}

async function approveListing(page: Page, listingLabel: string) {
  await page.getByRole('tab', { name: /Pending Listings/ }).click()
  const listingRow = page.locator('.verification-row').filter({ hasText: listingLabel })
  await expect(listingRow).toBeVisible()
  await listingRow.getByRole('button', { name: 'Approve', exact: true }).click()
  await expect(listingRow).toHaveCount(0)
}

async function submitRequestAndComplete(
  page: Page,
  listingButton: 'Request help' | 'Request stay',
  publicListingName: string,
  hub: string,
  roleName: string,
  partnerName: string,
  partnerEmail: string,
  partnerHeading: string,
) {
  const displaced = await register(page, 'My Support', 'Displaced')
  await page.getByRole('button', { name: 'Find Help', exact: true }).click()
  await page.getByRole('button', { name: 'Find Shelters', exact: true }).click()
  const listing = page.locator('.listing').filter({ hasText: publicListingName })
  await expect(listing).toBeVisible()
  await listing.getByRole('button', { name: listingButton, exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Help request submitted')
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await page.getByRole('button', { name: 'My Support', exact: true }).click()
  await signOut(page, displaced.name)
  await signIn(page, hub, roleName, partnerEmail, partnerHeading)
  const request = page.locator('.request-row:visible').first()
  await expect(request).toBeVisible()
  await request.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Request accepted')
  await expect(request.getByRole('button', { name: 'Complete', exact: true })).toBeVisible()
  await request.getByRole('button', { name: 'Complete', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Request completed')

  await signOut(page, partnerName)
  await signIn(page, 'My Support', 'Displaced', displaced.email, 'Welcome back!')
  await page.getByRole('button', { name: 'Ratings', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Share your experience.' })).toBeVisible()
  await page.getByLabel('Comment').fill('Helpful, respectful support.')
  await page.getByRole('button', { name: 'Submit rating', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Your rating was saved')
}

test.beforeEach(async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('button', { name: 'Find Help', exact: true })).toBeVisible()
})

test('registers and signs in a displaced user', async ({ page }) => {
  const account = await register(page, 'My Support', 'Displaced')
  await signOut(page, account.name)
  await signIn(page, 'My Support', 'Displaced', account.email, 'Welcome back!')
})

test('runs the shelter, NGO verification, moderation, request, acceptance, and rating journey', async ({ page }) => {
  const ngo = await register(page, 'Partner Hub', 'NGO')
  await expect(page.getByRole('button', { name: 'Submit for review' })).toBeDisabled()
  await signOut(page, ngo.name)
  const adminEmail = process.env.WARBRIDGE_E2E_ADMIN_EMAIL
  if (!adminEmail) throw new Error('Playwright did not configure the ephemeral E2E administrator.')
  await approvePartner(page, ngo.name)
  await expect(page.getByText('Total users', { exact: true })).toBeVisible()
  await signOut(page, 'Administrator')

  await signIn(page, 'Partner Hub', 'NGO', ngo.email, 'NGO Dashboard')
  await expect(page.getByRole('button', { name: 'Submit for review' })).toBeEnabled()
  const city = `Shelter City ${Date.now()}`
  await page.getByLabel('City', { exact: true }).first().fill(city)
  await page.getByLabel('Area', { exact: true }).fill('Central')
  await page.getByLabel('Address', { exact: true }).first().fill('Private address')
  await page.getByLabel('Beds available', { exact: true }).fill('3')
  await page.getByRole('button', { name: 'Submit for review', exact: true }).click()
  await expect(page.getByText('Pending admin review', { exact: true })).toBeVisible()
  await signOut(page, ngo.name)

  await signIn(page, 'Trust & Safety', 'Administrator', adminEmail, 'Admin Panel')
  await approveListing(page, city)
  await signOut(page, 'Administrator')
  await page.reload()
  await submitRequestAndComplete(page, 'Request help', `${city} Community Shelter`, 'Partner Hub', 'NGO', ngo.name, ngo.email, 'NGO Dashboard')
})

test('runs the host accommodation and request-handling journey', async ({ page }) => {
  const host = await register(page, 'Host Hub', 'Host')
  await signOut(page, host.name)
  await approvePartner(page, host.name)
  await signOut(page, 'Administrator')

  await signIn(page, 'Host Hub', 'Host', host.email, 'Host Dashboard')
  const city = `Host City ${Date.now()}`
  await page.getByLabel('City', { exact: true }).first().fill(city)
  await page.getByLabel('Area', { exact: true }).fill('Riverside')
  await page.locator('label').filter({ hasText: /^Address/ }).locator('input').fill('Private host address')
  await page.getByLabel('Rooms available', { exact: true }).fill('2')
  await page.getByRole('button', { name: 'Submit for review', exact: true }).click()
  await expect(page.getByText('Pending admin review', { exact: true })).toBeVisible()
  await signOut(page, host.name)
  await signIn(page, 'Trust & Safety', 'Administrator', process.env.WARBRIDGE_E2E_ADMIN_EMAIL!, 'Admin Panel')
  await approveListing(page, city)
  await signOut(page, 'Administrator')
  await page.reload()

  const displaced = await register(page, 'My Support', 'Displaced')
  await page.getByRole('button', { name: 'Find Help', exact: true }).click()
  await page.getByRole('button', { name: 'Host stays', exact: true }).click()
  const stay = page.locator('.listing').filter({ hasText: city })
  await expect(stay).toBeVisible()
  await stay.getByRole('button', { name: 'Request stay', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Help request submitted')
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await page.getByRole('button', { name: 'My Support', exact: true }).click()
  await signOut(page, displaced.name)
  await signIn(page, 'Host Hub', 'Host', host.email, 'Host Dashboard')
  const request = page.locator('.request-row:visible').first()
  await expect(request).toBeVisible()
  await request.getByRole('button', { name: 'Accept', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Request accepted')
})

test('submits SOS and keeps caller details private until a verified NGO claims it', async ({ page }) => {
  const ngo = await register(page, 'Partner Hub', 'NGO')
  await signOut(page, ngo.name)
  await approvePartner(page, ngo.name)
  await signOut(page, 'Administrator')
  await signIn(page, 'Partner Hub', 'NGO', ngo.email, 'NGO Dashboard')
  await page.getByRole('button', { name: 'SOS Queue', exact: true }).click()
  await page.getByRole('button', { name: 'Close dialog' }).click()
  await page.getByRole('button', { name: 'Find Help', exact: true }).click()
  await page.getByRole('button', { name: 'Emergency SOS', exact: true }).click()
  await page.getByLabel(/Name/).fill('Private SOS caller')
  await page.getByLabel(/Phone/).fill('555-0101')
  await page.getByLabel('Your location').fill('Private location')
  await page.getByRole('button', { name: 'Send SOS', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('SOS submitted')
  await page.getByRole('button', { name: 'Partner Hub', exact: true }).click()
  await signOut(page, ngo.name)
  await signIn(page, 'Partner Hub', 'NGO', ngo.email, 'NGO Dashboard')
  await page.getByRole('button', { name: 'SOS Queue', exact: true }).click()
  const sosRow = page.locator('.request-modal-row').filter({ hasText: 'Private SOS caller' })
  await expect(sosRow).toHaveCount(0)
  const visibleSos = page.locator('.request-modal-row').filter({ hasText: 'Emergency request' })
  await expect(visibleSos).toBeVisible()
  await visibleSos.getByRole('button', { name: 'View / claim', exact: true }).click()
  const detail = page.getByRole('dialog')
  await expect(detail).toContainText('Caller details are private')
  await expect(detail).not.toContainText('555-0101')
  await expect(detail).not.toContainText('Private location')
  await detail.getByRole('button', { name: 'Claim SOS', exact: true }).click()
  await expect(page.getByRole('dialog')).toBeHidden()
  await page.getByRole('button', { name: 'SOS Queue', exact: true }).click()
  await page.locator('.request-modal-row').getByRole('button', { name: 'View details', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('555-0101')
  await expect(page.getByRole('dialog')).toContainText('Private location')
})

test('publishes a partner alert and displays it publicly', async ({ page }) => {
  const ngo = await register(page, 'Partner Hub', 'NGO')
  await signOut(page, ngo.name)
  await approvePartner(page, ngo.name)
  await signOut(page, 'Administrator')
  await signIn(page, 'Partner Hub', 'NGO', ngo.email, 'NGO Dashboard')
  const title = `E2E food alert ${Date.now()}`
  await page.getByLabel('Title', { exact: true }).fill(title)
  await page.getByLabel('Message', { exact: true }).fill('Community meals are available today.')
  await page.getByRole('button', { name: 'Post alert', exact: true }).click()
  await expect(page.getByRole('status')).toContainText('Community alert posted')
  await page.getByRole('button', { name: 'Find Help', exact: true }).click()
  await page.getByRole('button', { name: 'Alerts', exact: true }).click()
  await expect(page.getByRole('heading', { name: title })).toBeVisible()
})

test('supports keyboard focus, accessible dialog states, labels, and reduced motion', async ({ page }) => {
  await page.getByRole('button', { name: 'Sign In', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: 'Sign in to WarBridge' })
  await expect(dialog).toBeVisible()
  await expect(dialog).toHaveAttribute('aria-modal', 'true')
  await expect(dialog).toBeFocused()

  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Close dialog' })).toBeFocused()
  await page.keyboard.press('Shift+Tab')
  await expect(page.getByRole('button', { name: 'Continue as a displaced person' })).toBeFocused()
  await page.keyboard.press('Tab')
  await expect(page.getByRole('button', { name: 'Close dialog' })).toBeFocused()

  await page.getByRole('tab', { name: 'Administrator' }).click()
  await page.getByLabel('Administrator username or email').fill('missing-admin@example.test')
  await page.getByLabel('Password').fill('incorrect-password')
  await page.getByRole('button', { name: 'Sign in', exact: true }).click()
  await expect(page.getByRole('alert')).toContainText('Invalid name or password')
  await page.keyboard.press('Escape')
  await expect(dialog).toBeHidden()
  await expect(page.getByRole('button', { name: 'Sign In', exact: true })).toBeFocused()

  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.getByRole('button', { name: 'Emergency SOS', exact: true }).click()
  const animationDuration = await page.locator('.modal-backdrop').evaluate(element => getComputedStyle(element).animationDuration)
  expect(animationDuration.split(',').every(duration => parseFloat(duration) <= 0.01)).toBe(true)
})

test('keeps the public and modal interfaces accessible with adequate contrast', async ({ page }) => {
  const results = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(results.violations).toEqual([])

  await page.getByRole('button', { name: 'Find Shelters', exact: true }).click()
  const modalResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(modalResults.violations).toEqual([])
})

test('fits mobile layouts and applies Arabic RTL when switching language', async ({ page }) => {
  await page.setViewportSize({ width: 375, height: 812 })
  const mobileWidth = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }))
  expect(mobileWidth.document).toBeLessThanOrEqual(mobileWidth.viewport)

  await page.getByRole('combobox', { name: 'Language' }).selectOption('ar')
  await expect(page.locator('html')).toHaveAttribute('dir', 'rtl')
  await expect(page.locator('html')).toHaveAttribute('lang', 'ar')
  const rtlWidth = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
  }))
  expect(rtlWidth.document).toBeLessThanOrEqual(rtlWidth.viewport)
  const rtlResults = await new AxeBuilder({ page })
    .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
    .analyze()
  expect(rtlResults.violations).toEqual([])
})