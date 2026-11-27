import { useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError } from './api'
import { availableLanguages, useI18n } from './i18n'

type IconName = 'home' | 'shield' | 'people' | 'bolt' | 'arrow' | 'bell' | 'chevron' | 'requests' | 'phone' | 'star' | 'report' | 'settings' | 'check' | 'clock' | 'bed' | 'medical' | 'alert' | 'megaphone' | 'user' | 'close' | 'search' | 'pin' | 'heart' | 'logout'
const paths: Record<IconName, ReactNode> = {
  home: <><path d="m3 11 9-8 9 8"/><path d="M5 10v11h5v-7h4v7h5V10"/></>,
  shield: <><path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6z"/><path d="m8 12 3 3 5-6"/></>,
  people: <><circle cx="9" cy="7" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3M17 4a3 3 0 0 1 0 6m1 4a5 5 0 0 1 3 5v2"/></>,
  bolt: <path d="m13 2-9 12h7l-1 8 10-13h-8z"/>,
  arrow: <path d="M4 12h16m-6-6 6 6-6 6"/>,
  bell: <><path d="M5 17h14l-2-4V8a5 5 0 0 0-10 0v5zM10 21h4"/><path d="M12 2v1"/></>,
  chevron: <path d="m8 10 4 4 4-4"/>,
  requests: <><path d="M9 5H5v16h14V5h-4M9 3h6v5H9zM8 12h8M8 16h6"/></>,
  phone: <path d="m5 3 4 1 1 5-3 2a15 15 0 0 0 6 6l2-3 5 1 1 4c-1 6-9 1-13-3S0 4 5 3Z"/>,
  star: <path d="m12 2 3 6.5 7 1-5 5 1.2 7-6.2-3.3-6.2 3.3 1.2-7-5-5 7-1z"/>,
  report: <><rect x="5" y="5" width="14" height="15" rx="2"/><path d="M9 2v6m6-6v6m-3 3v3m0 3v.1"/></>,
  settings: <><path d="m9 3-1 3-3 1-2 4 2 2v4l4 2 2 2 4-1 1-3 3-1 2-4-2-2V6l-4-2-2-2z"/><circle cx="12" cy="12" r="3"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  clock: <><circle cx="12" cy="12" r="9"/><path d="M12 6v6l4 3"/></>,
  bed: <><path d="M3 4v17m18-10v10M3 17h18M3 8h7v7H3m7-4h8a3 3 0 0 1 3 3v3"/></>,
  medical: <path d="M9 3h6v6h6v6h-6v6H9v-6H3V9h6z"/>,
  alert: <><path d="m12 3 10 18H2z"/><path d="M12 9v5m0 3v.2"/></>,
  megaphone: <><path d="m3 9 15-5v16L3 15zm15 0h3v6h-3M6 16l2 6h4l-2-5"/></>,
  user: <><circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/></>,
  close: <path d="m6 6 12 12M6 18 18 6"/>,
  search: <><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></>,
  pin: <><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 0 1 16 0Z"/><circle cx="12" cy="10" r="2.5"/></>,
  heart: <path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>,
  logout: <><path d="M9 3H3v18h6m5-14 5 5-5 5m-6-5h13"/></>,
}
function Icon({ name, size = 18, className = '' }: { name: IconName; size?: number; className?: string }) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className={`icon-${name} ${className}`} aria-hidden="true">{paths[name]}</svg>
}
function Logo({ label }: { label: string }) {
  return <span className="logo"><svg width="35" height="33" viewBox="0 0 40 38" fill="none" aria-hidden="true"><path d="M20 32 5 18C-5 6 13-3 20 10 27-3 45 6 35 18Z" stroke="currentColor" strokeWidth="3.5" strokeLinejoin="round"/><path d="m4 23 8-9 8 9 8-9 8 9M13 28l7-6 7 6" stroke="currentColor" strokeWidth="3.5" strokeLinejoin="round"/></svg><span>{label}</span></span>
}
type Modal = 'shelters' | 'accommodations' | 'services' | 'alerts' | 'about' | 'signin' | 'sos' | 'requests' | 'helplines' | 'ratings' | 'reports' | 'settings' | 'donate' | 'verification' | 'audit' | 'request-detail' | 'sos-queue' | null
type View = 'home' | 'displaced' | 'ngo' | 'host' | 'admin'
const views: { id: View; label: string }[] = [
  { id: 'home', label: 'Find Help' },
  { id: 'displaced', label: 'My Support' },
  { id: 'ngo', label: 'Partner Hub' },
  { id: 'host', label: 'Host Hub' },
  { id: 'admin', label: 'Trust & Safety' },
]
type RequestItem = { id: number; title: string; city: string; time: string; icon: IconName; accepted: boolean; urgent?: boolean; sos?: boolean; status?: string; contact?: string | null; requester_name?: string | null; location_text?: string | null; listing_type?: 'shelter' | 'accommodation'; listing_id?: number }
type AuthUser = { id: number; name: string; email: string; role: 'DISPLACED' | 'HOST' | 'NGO' | 'ADMIN'; verified: boolean; verification_status?: string; verification_expires_at?: string | null }
type AuthRole = AuthUser['role']
type VerificationItem = { id: number; name: string; role: string; time: string; created_at?: string; verification_status?: string; verification_review_notes?: string | null; verification_submitted_at?: string | null; verification_reviewed_at?: string | null; verification_expires_at?: string | null }
type FailedNotification = { id: number; request_id: number; channel: string; status: string; attempt_count: number; last_error_code: string | null; next_attempt_at: string | null; last_attempt_at: string | null; created_at: string; updated_at: string }
type AuditEntry = { action: string; target_type: string | null; target_id: number | null; created_at: string }
type ApiShelter = {
  id: number
  name: string
  city: string
  area: string
  beds_available: number
  women_safe: number
  rating: number
  rating_count: number
  updated_at: string
}
type ApiService = {
  id: number
  name: string
  category: string
  city: string
  opening_hours: string | null
  contact: string | null
  updated_at: string
}
type ApiAccommodation = {
  id: number
  city: string
  area: string
  rooms_available: number
  women_only: number
  description: string | null
  updated_at: string
}
type ApiAlert = { id: number; title: string; message: string; type: string; expires_at: string | null; partner_name: string }
type ManagedAlert = { id: number; title: string; message: string; type: string; expires_at: string | null; archived: number }
type OwnedListing = {
  id: number
  listing_type: 'shelter' | 'accommodation' | 'service'
  name?: string
  category?: string
  city: string
  area?: string
  address?: string
  phone?: string
  beds_available?: number
  rooms?: number
  rooms_available?: number
  women_safe?: number
  family_friendly?: number
  women_only?: number
  description?: string
  opening_hours?: string
  contact?: string
  verified: number
  blocked: number
  closed: number
}
type ApiRating = { listing_type: 'shelter' | 'accommodation'; listing_id: number; stars: number; comment: string | null }
type AdminAnalytics = {
  users: {
    total: number
    by_role: Record<'DISPLACED' | 'HOST' | 'NGO' | 'ADMIN', number>
    partners: Record<'NGO' | 'HOST', { verified: number; pending: number }>
  }
  requests: {
    by_status: Record<'pending' | 'accepted' | 'completed' | 'rejected' | 'cancelled', number>
    active_by_status: { pending: number; accepted: number }
    periods: Record<'last_7_days' | 'last_30_days' | 'last_90_days', { created: number; completed: number }>
  }
  listings: {
    available_shelter_beds: number
    available_accommodation_rooms: number
    open_reports: number
    blocked: number
    pending: number
  }
  sos: {
    unresolved: number
    average_response_seconds: number | null
    response_count: number
  }
  has_activity: boolean
}
type AdminAnalyticsState =
  | { status: 'loading' }
  | { status: 'empty'; data: AdminAnalytics }
  | { status: 'ready'; data: AdminAnalytics }
  | { status: 'error'; message: string }
  | { status: 'unauthorized' }
const localDateTimeInput = (value: string | null) => {
  if (!value) return ''
  const date = new Date(value)
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16)
}

export default function App() {
  const { language, setLanguage, t, formatDate, formatNumber, formatPhone } = useI18n()
  const [view, setView] = useState<View>('home')
  const [modal, setModal] = useState<Modal>(null)
  const [toast, setToast] = useState('')
  const [requests, setRequests] = useState<RequestItem[]>([])
  const [verifications, setVerifications] = useState<VerificationItem[]>([])
  const [failedNotifications, setFailedNotifications] = useState<FailedNotification[]>([])
  const [adminTab, setAdminTab] = useState('Pending Verifications')
  const [alertText, setAlertText] = useState('')
  const [alertTitle, setAlertTitle] = useState('')
  const [alertType, setAlertType] = useState('Warning')
  const [alertExpiresAt, setAlertExpiresAt] = useState('')
  const [alerts, setAlerts] = useState<ApiAlert[]>([])
  const [managedAlerts, setManagedAlerts] = useState<ManagedAlert[]>([])
  const [ownedListings, setOwnedListings] = useState<OwnedListing[]>([])
  const [ratings, setRatings] = useState<ApiRating[]>([])
  const [apiShelters, setApiShelters] = useState<ApiShelter[]>([])
  const [apiAccommodations, setApiAccommodations] = useState<ApiAccommodation[]>([])
  const [apiServices, setApiServices] = useState<ApiService[]>([])
  const [city, setCity] = useState('')
  const [womenOnly, setWomenOnly] = useState(false)
  const [requested, setRequested] = useState<string[]>([])
  const [selectedRequest, setSelectedRequest] = useState<RequestItem | null>(null)
  const [selectedOrg, setSelectedOrg] = useState('')
  const [selectedOrgId, setSelectedOrgId] = useState<number | null>(null)
  const [verificationNotes, setVerificationNotes] = useState('')
  const [verificationExpiresAt, setVerificationExpiresAt] = useState('')
  const [authUser, setAuthUser] = useState<AuthUser | null>(null)
  const [authRole, setAuthRole] = useState<AuthRole>('NGO')
  const [authMode, setAuthMode] = useState<'signin' | 'register'>('signin')
  const [authIdentity, setAuthIdentity] = useState('')
  const [authEmail, setAuthEmail] = useState('')
  const [authPassword, setAuthPassword] = useState('')
  const [authGender, setAuthGender] = useState('')
  const [listingCity, setListingCity] = useState('')
  const [listingArea, setListingArea] = useState('')
  const [listingAddress, setListingAddress] = useState('')
  const [listingCapacity, setListingCapacity] = useState('1')
  const [serviceName, setServiceName] = useState('')
  const [serviceCategory, setServiceCategory] = useState('Food')
  const [serviceCity, setServiceCity] = useState('')
  const [serviceAddress, setServiceAddress] = useState('')
  const [serviceHours, setServiceHours] = useState('')
  const [serviceContact, setServiceContact] = useState('')
  const [authError, setAuthError] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [auditEntries, setAuditEntries] = useState<AuditEntry[]>([])
  const [adminSos, setAdminSos] = useState<RequestItem[]>([])
  const [adminReports, setAdminReports] = useState<{ id: number; listing_type: string; listing_id: number; reason: string }[]>([])
  const [pendingListings, setPendingListings] = useState<{ id: number; listing_type: string; label: string; owner_name: string }[]>([])
  const [blockedListings, setBlockedListings] = useState<{ id: number; listing_type: string; label: string; owner_name: string }[]>([])
  const [adminAnalytics, setAdminAnalytics] = useState<AdminAnalyticsState>({ status: 'loading' })
  const modalRef = useRef<HTMLElement>(null)
  useEffect(() => {
    if (!modal) return
    const previousFocus = document.activeElement as HTMLElement | null
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    modalRef.current?.focus()
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setModal(null)
      if (event.key !== 'Tab') return
      const controls = modalRef.current?.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], input, textarea, select')
      if (!controls?.length) return
      const first = controls[0]
      const last = controls[controls.length - 1]
      if (event.shiftKey && (document.activeElement === first || document.activeElement === modalRef.current)) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => {
      document.body.style.overflow = previousOverflow
      document.removeEventListener('keydown', handleKey)
      previousFocus?.focus()
    }
  }, [modal])
  const notify = (message: string) => { setToast(t(message)); window.setTimeout(() => setToast(''), 4500) }
  const loadAdminAnalytics = () => {
    setAdminAnalytics({ status: 'loading' })
    void api.get<AdminAnalytics>('/api/admin/analytics')
      .then(data => setAdminAnalytics({ status: data.has_activity ? 'ready' : 'empty', data }))
      .catch(error => {
        if (error instanceof ApiError && (error.status === 401 || error.status === 403)) {
          setAdminAnalytics({ status: 'unauthorized' })
          return
        }
        setAdminAnalytics({
          status: 'error',
          message: error instanceof Error ? error.message : 'Could not load platform analytics.',
        })
      })
  }
  const loadRoleData = (user: AuthUser) => {
    if (user.role === 'ADMIN') {
      loadAdminAnalytics()
      void Promise.all([
        api.get<{ users: VerificationItem[] }>('/api/admin/verifications'),
        api.get<{ audit: AuditEntry[] }>('/api/admin/audit'),
        api.get<{ requests: { id: number; status: string; created_at: string; contact?: string | null; location_text?: string | null; requester_name?: string | null }[] }>('/api/admin/sos'),
        api.get<{ reports: { id: number; listing_type: string; listing_id: number; reason: string }[] }>('/api/admin/reports'),
        api.get<{ listings: { id: number; listing_type: string; label: string; owner_name: string }[] }>('/api/admin/listings/pending'),
        api.get<{ listings: { id: number; listing_type: string; label: string; owner_name: string }[] }>('/api/admin/listings/blocked'),
        api.get<{ notifications: FailedNotification[] }>('/api/admin/notifications/failed'),
      ]).then(([verificationResult, auditResult, sosResult, reportsResult, pendingResult, blockedResult, notificationResult]) => {
        setVerifications(verificationResult.users.map(partner => ({
          ...partner,
          time: partner.created_at ? formatDate(partner.created_at) : '',
        })))
        setAuditEntries(auditResult.audit)
        setAdminSos(sosResult.requests.map(item => ({
          id: item.id,
          title: t('Emergency request'),
          city: item.status === 'Escalated' ? item.location_text || t('Location not provided') : t('Private details available after escalation'),
          time: formatDate(item.created_at, true),
          icon: 'alert',
          accepted: item.status === 'Escalated',
          urgent: true,
          sos: true,
          status: item.status,
          contact: item.contact,
          requester_name: item.requester_name,
          location_text: item.location_text,
        })))
        setAdminReports(reportsResult.reports)
        setPendingListings(pendingResult.listings)
        setBlockedListings(blockedResult.listings)
        setFailedNotifications(notificationResult.notifications)
      }).catch(error => notify(error instanceof Error ? error.message : 'Could not load administrator records.'))
    } else if (user.role === 'NGO') {
      void Promise.all([
        api.get<{ requests: { id: number; type: string; location_text?: string | null; created_at: string; status: string }[] }>('/api/requests/incoming'),
        api.get<{ requests: { id: number; status: string; location_text?: string | null; contact?: string | null; requester_name?: string | null; created_at: string; claimed_by?: number | null }[] }>('/api/sos/incoming'),
        api.get<{ listings: OwnedListing[] }>('/api/listings/mine'),
        api.get<{ alerts: ManagedAlert[] }>('/api/alerts/mine'),
      ]).then(([requestResult, sosResult, listingsResult, alertsResult]) => {
        setOwnedListings(listingsResult.listings)
        setManagedAlerts(alertsResult.alerts)
        setRequests([
          ...requestResult.requests.map(item => ({
          id: item.id,
          title: t('{type} request', { type: t(item.type) }),
          city: item.location_text || t('Location shared after acceptance'),
          time: formatDate(item.created_at, true),
          icon: 'bed' as IconName,
          accepted: item.status === 'Accepted',
          status: item.status,
        })),
        ...sosResult.requests.map(item => ({
          id: item.id,
          title: t('Emergency request'),
          city: item.location_text || t('Location available after claim'),
          time: formatDate(item.created_at, true),
          icon: 'alert' as IconName,
          urgent: true,
          sos: true,
          accepted: Boolean(item.claimed_by),
          status: item.status,
          contact: item.contact,
          requester_name: item.requester_name,
          location_text: item.location_text,
        })),
        ])
      })
        .catch(error => notify(error instanceof Error ? error.message : 'Could not load incoming requests.'))
    } else if (user.role === 'HOST') {
      void Promise.all([
        api.get<{ requests: { id: number; type: string; location_text?: string | null; created_at: string; status: string }[] }>('/api/requests/incoming'),
        api.get<{ listings: OwnedListing[] }>('/api/listings/mine'),
      ]).then(([result, listingsResult]) => {
        setOwnedListings(listingsResult.listings)
        setRequests(result.requests.map(item => ({
          id: item.id,
          title: t('{type} request', { type: t(item.type) }),
          city: item.location_text || t('Location shared after acceptance'),
          time: formatDate(item.created_at, true),
          icon: 'home',
          accepted: item.status === 'Accepted',
          status: item.status,
        })))
      })
        .catch(error => notify(error instanceof Error ? error.message : 'Could not load incoming requests.'))
    } else {
      void Promise.all([
        api.get<{ requests: { id: number; type: string; status: string; created_at: string; shelter_id: number | null; accommodation_id: number | null; shelter_name?: string; shelter_area?: string }[] }>('/api/requests/mine'),
        api.get<{ ratings: ApiRating[] }>('/api/ratings/mine'),
      ]).then(([result, ratingsResult]) => {
        setRatings(ratingsResult.ratings)
        setRequests(result.requests.map(item => ({
          id: item.id,
          title: t('{type} request', { type: t(item.type) }),
          city: item.shelter_name || item.shelter_area || t('Your support request'),
          time: formatDate(item.created_at, true),
          icon: 'bed',
          accepted: item.status === 'Accepted',
          status: item.status,
          listing_type: item.shelter_id ? 'shelter' : item.accommodation_id ? 'accommodation' : undefined,
          listing_id: item.shelter_id || item.accommodation_id || undefined,
        })))
      })
        .catch(error => notify(error instanceof Error ? error.message : 'Could not load your requests.'))
    }
  }
  useEffect(() => {
    void api.get<{ user: AuthUser | null }>('/api/auth/me')
      .then(({ user }) => {
        if (!user) return
        setAuthUser(user)
        setView(user.role === 'NGO' ? 'ngo' : user.role === 'HOST' ? 'host' : user.role === 'ADMIN' ? 'admin' : 'displaced')
        loadRoleData(user)
      })
      .catch(error => setAuthError(error instanceof Error ? error.message : 'Unable to restore your sign-in session.'))
  }, [])
  const previousLanguage = useRef(language)
  useEffect(() => {
    if (previousLanguage.current === language) return
    previousLanguage.current = language
    if (authUser) loadRoleData(authUser)
  }, [language, authUser])
  useEffect(() => {
    void Promise.all([
      api.get<{ shelters: ApiShelter[] }>('/api/public/shelters'),
      api.get<{ accommodations: ApiAccommodation[] }>('/api/public/accommodations'),
      api.get<{ alerts: ApiAlert[] }>('/api/public/alerts'),
      api.get<{ services: ApiService[] }>('/api/public/services'),
    ]).then(([shelterResponse, accommodationResponse, alertResponse, serviceResponse]) => {
      setApiShelters(shelterResponse.shelters)
      setApiAccommodations(accommodationResponse.accommodations)
      setAlerts(alertResponse.alerts)
      setApiServices(serviceResponse.services)
    }).catch(() => {
      notify('Could not load public listings. Check that the backend is running.')
    })
  }, [])
  const open = (value: Modal) => setModal(value)
  const navigateView = (target: View) => {
    const requiredRole: AuthRole | null = target === 'ngo' ? 'NGO' : target === 'host' ? 'HOST' : target === 'admin' ? 'ADMIN' : target === 'displaced' ? 'DISPLACED' : null
    if (requiredRole && authUser?.role !== requiredRole) {
      setAuthRole(requiredRole)
      setAuthMode('signin')
      setAuthError('')
      setModal('signin')
      return
    }
    setView(target)
  }
  const accept = (id: number) => {
    void api.post(`/api/requests/${id}/accept`).then(() => {
      if (authUser) loadRoleData(authUser)
      notify('Request accepted.')
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not accept request.'))
  }
  const updateRequest = (id: number, action: 'reject' | 'complete' | 'cancel') => {
    const path = action === 'cancel' ? `/api/requests/${id}/cancel` : `/api/requests/${id}/${action}`
    void api.post(path).then(() => {
      if (authUser) loadRoleData(authUser)
      notify(`Request ${action === 'cancel' ? 'cancelled' : action === 'complete' ? 'completed' : 'rejected'}.`)
      setModal(null)
    }).catch(error => notify(error instanceof Error ? error.message : `Could not ${action} this request.`))
  }
  const claimSos = (id: number) => {
    void api.post(`/api/sos/${id}/claim`).then(() => {
      if (authUser) loadRoleData(authUser)
      notify('SOS claimed. Contact details are now available to your NGO.')
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not claim this SOS.'))
  }
  const updateSos = (id: number, action: 'escalate' | 'resolve') => {
    void api.post(`/api/sos/${id}/${action}`).then(() => {
      if (authUser) loadRoleData(authUser)
      notify(action === 'resolve' ? 'SOS marked resolved.' : 'SOS escalated for administrator review.')
      setModal(null)
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not update this SOS.'))
  }
  const decide = (id: number, approved: boolean, notes = '', expiry = '') => {
    const org = verifications.find(v => v.id === id)
    const body = approved
      ? { review_notes: notes, expires_at: expiry ? new Date(expiry).toISOString() : null }
      : { review_notes: notes }
    void api.post(`/api/admin/users/${id}/${approved ? 'verify' : 'reject'}`, body).then(() => {
      setVerifications(items => items.filter(v => v.id !== id))
      notify(`${org?.name ?? 'Partner'} ${approved ? 'approved' : 'rejected'}.`)
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not update partner.'))
  }
  const startVerificationReview = (id: number) => {
    void api.post(`/api/admin/users/${id}/review`, { review_notes: verificationNotes })
      .then(() => {
        if (authUser) loadRoleData(authUser)
        notify('Verification review started.')
      })
      .catch(error => notify(error instanceof Error ? error.message : 'Could not start verification review.'))
  }
  const moderateListing = (listing: { id: number; listing_type: string; label: string }, action: 'approve' | 'block' | 'unblock') => {
    void api.post(`/api/admin/listings/${listing.listing_type}/${listing.id}/${action}`).then(() => {
      if (authUser) loadRoleData(authUser)
      notify(`${listing.label} ${action === 'approve' ? 'approved' : action === 'block' ? 'blocked' : 'unblocked'}.`)
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not update the listing.'))
  }
  const decideReport = (id: number, action: 'block' | 'dismiss') => {
    void api.post(`/api/admin/reports/${id}/${action}`).then(() => {
      if (authUser) loadRoleData(authUser)
      notify(`Report ${action === 'block' ? 'actioned' : 'dismissed'}.`)
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not update the report.'))
  }
  const retryNotification = (id: number) => {
    void api.post(`/api/admin/notifications/${id}/retry`).then(() => {
      if (authUser) loadRoleData(authUser)
      notify('Emergency notification retry completed.')
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not retry this notification.'))
  }
  const signIn = (event: FormEvent) => {
    event.preventDefault()
    setAuthError('')
    setAuthBusy(true)
    void api.post<{ user: AuthUser; csrfToken: string }>('/api/auth/login', {
      identity: authIdentity,
      password: authPassword,
      role: authRole,
    }).then(({ user, csrfToken }) => {
      api.setCsrfToken(csrfToken)
      setAuthUser(user)
      setAuthPassword('')
      setModal(null)
      setView(user.role === 'ADMIN' ? 'admin' : user.role === 'NGO' ? 'ngo' : user.role === 'HOST' ? 'host' : 'displaced')
      loadRoleData(user)
      if ((user.role === 'NGO' || user.role === 'HOST') && !user.verified) {
        notify('Your account is awaiting administrator verification. Access is read-only.')
      } else {
        notify(`Signed in as ${user.name}.`)
      }
    }).catch(error => setAuthError(error instanceof Error ? error.message : 'Sign-in failed.'))
      .finally(() => setAuthBusy(false))
  }
  const registerAccount = (event: FormEvent) => {
    event.preventDefault()
    setAuthError('')
    setAuthBusy(true)
    void api.post<{ user: AuthUser; csrfToken: string }>('/api/auth/register', {
      name: authIdentity,
      email: authEmail,
      password: authPassword,
      role: authRole,
      gender: authGender || undefined,
    }).then(({ user, csrfToken }) => {
      api.setCsrfToken(csrfToken)
      setAuthUser(user)
      setAuthPassword('')
      setModal(null)
      setView(user.role === 'HOST' ? 'host' : user.role === 'DISPLACED' ? 'displaced' : 'ngo')
      loadRoleData(user)
      notify(user.role === 'DISPLACED' ? 'Your account is ready.' : `${user.role} account created. Administrator verification is required before partner actions.`)
    }).catch(error => setAuthError(error instanceof Error ? error.message : 'Account could not be created.'))
      .finally(() => setAuthBusy(false))
  }
  const createPartnerListing = (event: FormEvent) => {
    event.preventDefault()
    const host = authUser?.role === 'HOST'
    void api.post(host ? '/api/accommodations' : '/api/shelters', host
    ? { city: listingCity, area: listingArea, address: listingAddress, rooms: Number(listingCapacity) }
    : { name: `${listingCity} Community Shelter`, city: listingCity, area: listingArea, address: listingAddress, beds_available: Number(listingCapacity) })
    .then(() => {
      setListingCity('')
      setListingArea('')
      setListingAddress('')
      setListingCapacity('1')
      notify('Listing submitted for administrator review.')
      if (authUser) loadRoleData(authUser)
    })
    .catch(error => notify(error instanceof Error ? error.message : 'Could not submit the listing.'))
  }
  const createService = (event: FormEvent) => {
    event.preventDefault()
    void api.post('/api/services', {
      name: serviceName,
      category: serviceCategory,
      city: serviceCity,
      opening_hours: serviceHours,
      contact: serviceContact,
      address: serviceAddress,
    }).then(() => {
      setServiceName('')
      setServiceHours('')
      setServiceContact('')
      setServiceCity('')
      setServiceAddress('')
      notify('Service submitted for administrator review.')
      if (authUser) loadRoleData(authUser)
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not submit the service.'))
  }
  const updateOwnedListing = (event: FormEvent<HTMLFormElement>, listing: OwnedListing) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const payload: Record<string, unknown> = {
      city: form.get('city'),
      address: form.get('address'),
    }
    if (listing.listing_type === 'shelter') {
      Object.assign(payload, {
        name: form.get('name'),
        area: form.get('area'),
        phone: form.get('phone'),
        beds_available: Number(form.get('beds_available')),
        women_safe: form.get('women_safe') === 'on',
        family_friendly: form.get('family_friendly') === 'on',
      })
    } else if (listing.listing_type === 'accommodation') {
      Object.assign(payload, {
        area: form.get('area'),
        rooms: Number(form.get('rooms')),
        women_only: form.get('women_only') === 'on',
        description: form.get('description'),
      })
    } else {
      Object.assign(payload, {
        name: form.get('name'),
        category: form.get('category'),
        opening_hours: form.get('opening_hours'),
        contact: form.get('contact'),
      })
    }
    void api.patch(`/api/listings/${listing.listing_type}/${listing.id}`, payload)
      .then(() => {
        if (authUser) loadRoleData(authUser)
        notify('Listing updated.')
      })
      .catch(error => notify(error instanceof Error ? error.message : 'Could not update the listing.'))
  }
  const changeListingStatus = (listing: OwnedListing) => {
    const action = listing.closed ? 'reopen' : 'close'
    void api.post(`/api/listings/${listing.listing_type}/${listing.id}/${action}`)
      .then(() => {
        if (authUser) loadRoleData(authUser)
        notify(`Listing ${action === 'close' ? 'closed' : 'reopened'}.`)
      })
      .catch(error => notify(error instanceof Error ? error.message : 'Could not change listing status.'))
  }
  const postAlert = (event: FormEvent) => {
    event.preventDefault()
    if (!alertTitle.trim() || !alertText.trim()) return
    void api.post('/api/alerts', {
      title: alertTitle.trim(),
      message: alertText.trim(),
      type: alertType,
      expires_at: alertExpiresAt ? new Date(alertExpiresAt).toISOString() : null,
    })
      .then(() => {
        setAlertTitle('')
        setAlertText('')
        setAlertExpiresAt('')
        notify('Community alert posted.')
        if (authUser) loadRoleData(authUser)
        void api.get<{ alerts: ApiAlert[] }>('/api/public/alerts').then(result => setAlerts(result.alerts))
      })
      .catch(error => notify(error instanceof Error ? error.message : 'Could not post this alert.'))
  }
  const updateAlert = (event: FormEvent<HTMLFormElement>, alert: ManagedAlert) => {
    event.preventDefault()
    const form = new FormData(event.currentTarget)
    const expiresValue = String(form.get('expires_at') || '')
    void api.patch(`/api/alerts/${alert.id}`, {
      title: form.get('title'),
      message: form.get('message'),
      type: form.get('type'),
      expires_at: expiresValue ? new Date(expiresValue).toISOString() : null,
    }).then(() => {
      if (authUser) loadRoleData(authUser)
      void api.get<{ alerts: ApiAlert[] }>('/api/public/alerts').then(result => setAlerts(result.alerts))
      notify('Alert updated.')
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not update the alert.'))
  }
  const archiveAlert = (alert: ManagedAlert) => {
    void api.post(`/api/alerts/${alert.id}/archive`).then(() => {
      if (authUser) loadRoleData(authUser)
      void api.get<{ alerts: ApiAlert[] }>('/api/public/alerts').then(result => setAlerts(result.alerts))
      notify('Alert archived.')
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not archive this alert.'))
  }
  const submitRating = (event: FormEvent<HTMLFormElement>, item: RequestItem) => {
    event.preventDefault()
    if (!item.listing_type || !item.listing_id) return
    const form = new FormData(event.currentTarget)
    void api.post('/api/ratings', {
      listing_type: item.listing_type,
      listing_id: item.listing_id,
      stars: Number(form.get('stars')),
      comment: form.get('comment'),
    }).then(() => {
      notify('Your rating was saved.')
      if (authUser) loadRoleData(authUser)
    }).catch(error => notify(error instanceof Error ? error.message : 'Could not submit your rating.'))
  }
  const navAction = (label: string) => {
    const map: Record<string, Modal> = { 'My Requests': 'requests', 'Help Requests': 'requests', 'Safety Helplines': 'helplines', Ratings: 'ratings', Reports: 'reports', Settings: 'settings', Shelters: 'shelters', Accommodations: 'accommodations', Services: 'services', Alerts: 'alerts', Verification: 'verification', 'Audit Log': 'audit', 'SOS Queue': 'sos-queue' }
    if (label !== 'Dashboard') open(map[label] || 'about')
  }
  function Sidebar({ role, items, active = 'Dashboard' }: { role: 'user' | 'ngo' | 'host' | 'admin'; items: [IconName, string][]; active?: string }) {
    const partner = role === 'ngo' || role === 'host'
    return <aside className="sidebar"><Logo label={t('WarBridge')}/><nav aria-label={t(`${role} navigation`)}>{items.map(([icon, label]) => <button key={label} className={`side-link ${label === active ? 'active' : ''}`} onClick={() => navAction(label)}><Icon name={icon} /><span>{t(label)}</span></button>)}</nav><div className="sidebar-status"><span className="status-check"><Icon name="check" size={13}/></span><div><strong>{partner ? `${t(role === 'host' ? 'Host' : 'NGO')} ${t(authUser?.verification_status || (authUser?.verified ? 'Approved' : 'Submitted'))}` : role === 'admin' ? t('System Status') : t('Verified User')}</strong><small>{partner ? (authUser?.verified ? t('Trusted Partner') : t('Read-only access')) : role === 'admin' ? t('All systems operational') : t('Stay Safe Together')}</small></div></div></aside>
  }
  function Profile({ name, initial }: { name: string; initial: string }) {
    return <button className="profile" onClick={() => open('settings')}><span className="avatar">{initial}</span><span>{name}</span><Icon name="chevron" size={12}/></button>
  }
  function Helplines({ full = false }: { full?: boolean }) {
    return <div className={`helpline-list ${full ? 'full' : ''}`}>{([{ name: 'Women Helpline', number: '181', icon: 'phone' }, { name: 'Emergency Response', number: '112', icon: 'phone' }, { name: 'Child Helpline', number: '1098', icon: 'shield' }] as { name: string; number: string; icon: IconName }[]).map(item => <a key={item.number} href={`tel:${item.number}`}><span className="helpline-icon"><Icon name={item.icon} size={22}/></span><span>{t(item.name)}<strong>{formatPhone(item.number)}</strong></span></a>)}</div>
  }
  const renderAdminAnalytics = () => {
    if (adminAnalytics.status === 'loading') {
      return <p className="analytics-state" role="status">{t("Loading platform analytics…")}</p>
    }
    if (adminAnalytics.status === 'unauthorized') {
      return <p className="analytics-state analytics-error" role="alert">{t("Administrator access is required to view analytics. Sign in with an admin account.")}</p>
    }
    if (adminAnalytics.status === 'error') {
      return <div className="analytics-state analytics-error" role="alert"><p>{adminAnalytics.message}</p><button className="outline-button" onClick={loadAdminAnalytics}>{t("Try again")}</button></div>
    }

    const data = adminAnalytics.data
    const metric = (label: string, value: ReactNode, detail?: string) => (
      <div className="analytics-metric" key={label}>
        <span>{t(label)}</span>
        <strong>{typeof value === 'number' ? formatNumber(value) : value}</strong>
        {detail && <small>{detail}</small>}
      </div>
    )
    const averageResponse = data.sos.average_response_seconds === null
      ? t('No claimed SOS yet')
      : data.sos.average_response_seconds < 60
        ? `${formatNumber(data.sos.average_response_seconds)} sec`
        : `${formatNumber(data.sos.average_response_seconds / 60, { maximumFractionDigits: 1 })} min`

    return <>
      {adminAnalytics.status === 'empty' && <p className="analytics-state" role="status">{t("No platform activity recorded yet. Metrics will update as users and requests are added.")}</p>}
      <div className="analytics-grid">
        <section className="analytics-section">
          <h4>{t("Users & partners")}</h4>
          <div className="analytics-metrics">
            {metric('Total users', data.users.total)}
            {metric('Displaced people', data.users.by_role.DISPLACED)}
            {metric('NGOs', data.users.by_role.NGO, t('{verified} verified · {pending} pending', { verified: formatNumber(data.users.partners.NGO.verified), pending: formatNumber(data.users.partners.NGO.pending) }))}
            {metric('Hosts', data.users.by_role.HOST, t('{verified} verified · {pending} pending', { verified: formatNumber(data.users.partners.HOST.verified), pending: formatNumber(data.users.partners.HOST.pending) }))}
            {metric('Administrators', data.users.by_role.ADMIN)}
          </div>
        </section>
        <section className="analytics-section">
          <h4>{t("Requests by status")}</h4>
          <div className="analytics-metrics">
            {metric('Pending', data.requests.active_by_status.pending)}
            {metric('Accepted', data.requests.active_by_status.accepted)}
            {metric('Completed', data.requests.by_status.completed)}
            {metric('Rejected', data.requests.by_status.rejected)}
            {metric('Cancelled', data.requests.by_status.cancelled)}
          </div>
        </section>
        <section className="analytics-section">
          <h4>{t("Capacity & trust")}</h4>
          <div className="analytics-metrics">
            {metric('Available shelter beds', data.listings.available_shelter_beds)}
            {metric('Available host rooms', data.listings.available_accommodation_rooms)}
            {metric('Open reports', data.listings.open_reports)}
            {metric('Blocked listings', data.listings.blocked)}
            {metric('Pending listings', data.listings.pending)}
          </div>
        </section>
        <section className="analytics-section">
          <h4>{t("SOS response")}</h4>
          <div className="analytics-metrics">
            {metric('Unresolved SOS', data.sos.unresolved)}
            {metric('Average response', averageResponse, t('{count} claimed SOS requests', { count: formatNumber(data.sos.response_count) }))}
          </div>
        </section>
        <section className="analytics-section analytics-period-section">
          <h4>{t("Requests created & completed")}</h4>
          <div className="analytics-periods">
            {([
              ['Last 7 days', data.requests.periods.last_7_days],
              ['Last 30 days', data.requests.periods.last_30_days],
              ['Last 90 days', data.requests.periods.last_90_days],
            ] as const).map(([label, period]) => (
              <div className="analytics-period" key={label}>
                <strong>{label}</strong>
                <span>{formatNumber(period.created)} {' '}{t("created")}</span>
                <span>{formatNumber(period.completed)} {' '}{t("completed")}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </>
  }

  return <div className="app-shell">
    <header className="view-header"><nav className="view-navigation" aria-label={t("WarBridge pages")}>{views.map(item => <button key={item.id} aria-pressed={view === item.id} className={view === item.id ? 'current-view' : ''} onClick={() => navigateView(item.id)}>{t(item.label)}</button>)}</nav><label className="language-picker"><span className="sr-only">{t('Language')}</span><select aria-label={t('Language')} value={language} onChange={event => setLanguage(event.target.value as typeof language)}>{availableLanguages.map(code => <option key={code} value={code}>{t(code === 'en' ? 'English' : code === 'hi' ? 'Hindi (draft)' : 'Arabic (draft)')}</option>)}</select></label><span className="preview-label"><span className="live-dot"/> {' '}{t("WarBridge")}</span></header>
    <main className="showcase page-layout">
    <section className="panel landing purple" hidden={view !== 'home'} aria-label={t("WarBridge public home")}>
      <div className="landing-image" /><div className="orbital orbital-one"/><div className="orbital orbital-two"/>
      <header className="landing-nav"><Logo label={t('WarBridge')}/><nav aria-label={t("Public navigation")}><button onClick={() => open('shelters')}>{t("Shelters")}</button><button onClick={() => open('accommodations')}>{t("Host stays")}</button><button onClick={() => open('services')}>{t("Services")}</button><button onClick={() => open('alerts')}>{t("Alerts")}</button><button onClick={() => open('about')}>{t("About")}</button></nav><button className="sign-in" onClick={() => { setAuthRole('NGO'); setAuthMode('signin'); setAuthError(''); open('signin') }}>{t("Sign In")}</button></header>
      <div className="hero-copy"><div className="eyebrow"><span/> {' '}{t("A bridge to a safer tomorrow")}</div><h1>{t("War")}<span>{t("Bridge")}</span></h1><h2>{t("Find help.")}{' '}<span>{t("Stay safe.")}</span></h2><p>{t("Verified shelters, food, healthcare and more —")}<br className="desktop-break"/> {' '}{t("for people in need.")}</p><div className="hero-actions"><button className="primary purple-button" onClick={() => open('shelters')}>{t("Find Shelters")}{' '}<Icon name="arrow" size={17}/></button><button className="sos-button" onClick={() => open('sos')}><Icon name="alert" size={22}/> {' '}{t("Emergency SOS")}</button></div><div className="trust-row"><div><span className="trust-icon"><Icon name="shield" size={24}/></span><span>{t("Verified")}<br/>{t("Shelters")}</span></div><div><span className="trust-icon"><Icon name="people" size={24}/></span><span>{t("Trusted")}<br/>{t("NGOs & Hosts")}</span></div><div><span className="trust-icon"><Icon name="bolt" size={24}/></span><span>{t("Real-Time")}<br/>{t("Alerts")}</span></div></div></div>
      <span className="landing-footnote"><span className="live-dot"/> {' '}{t("Human connection. Real hope.")}</span>
    </section>

    <section className="panel dashboard green" hidden={view !== 'displaced'} aria-label={t("Displaced user dashboard")}>
      <div className="dashboard-landscape"/><div className="orbital orbital-one"/>
      <Sidebar role="user" items={[['home', 'Dashboard'], ['requests', 'My Requests'], ['phone', 'Safety Helplines'], ['star', 'Ratings'], ['report', 'Reports'], ['settings', 'Settings']]}/>
      <div className="dashboard-main user-main">
        <div className="topbar"><span className="workspace-label">{t("YOUR SAFE SPACE")}</span><div className="topbar-right"><button className="notification" aria-label={t("View notifications")} onClick={() => open('alerts')}><Icon name="bell"/><span>{alerts.length}</span></button><Profile name={authUser?.name || 'User'} initial={(authUser?.name || 'U').slice(0, 1).toUpperCase()}/></div></div>
        <div className="welcome"><div><h2>{t("Welcome back!")}</h2><p>{t("You’re not alone. Help is here.")}</p></div><span className="verified-badge"><Icon name="shield" size={16}/> {' '}{t("Verified User")}</span></div>
        <div className="stats-grid"><div className="stat"><span className="stat-icon"><Icon name="home" size={31}/></span><div><strong>{requests.filter(item => item.status === 'Pending' || item.status === 'Accepted').length}</strong><small>{t("Active Requests")}</small></div></div><div className="stat"><span className="stat-icon gold"><Icon name="star" size={30}/></span><div><strong>{t("—")}</strong><small>{t("Rating available after completion")}</small></div></div><div className="stat"><span className="stat-icon"><Icon name="people" size={31}/></span><div><strong>{t("—")}</strong><small>{t("Reports filed")}</small></div></div></div>
        <div className="user-middle"><div className="surface help-progress"><div className="section-heading"><h3>{t("Your Help Requests")}</h3><button className="text-link" onClick={() => open('requests')}>{t("View all")}{' '}<Icon name="arrow" size={13}/></button></div><div className="request-list">{requests.length ? requests.map(item => <article className="request-row" key={`mine-${item.id}`}><span className="request-icon"><Icon name={item.icon} size={24}/></span><div className="request-info"><strong>{item.title}</strong><small>{item.city} {' '}{t("·")}{' '}{item.status ? t(item.status || 'Unknown') : t("Unknown")}</small></div></article>) : <div className="empty-state"><p>{t("Your request activity will appear here.")}</p></div>}</div></div><div className="surface helplines-card"><h3>{t("Safety Helplines")}</h3><Helplines/><button className="text-link helplines-more" onClick={() => open('helplines')}>{t("View More")}{' '}<Icon name="arrow" size={11}/></button></div></div>
        <div className="impact-banner"><div className="banner-art"><Icon name="heart" size={64}/></div><div><h3>{t("Together, we can rebuild.")}</h3><p>{t("Support. Shelter. Hope.")}</p></div><button className="primary" onClick={() => open('donate')}>{t("Get involved")}{' '}<Icon name="arrow" size={13}/></button></div>
      </div>
    </section>

    <section className="panel dashboard red" hidden={view !== 'ngo' && view !== 'host'} aria-label={authUser?.role === 'HOST' ? 'Host dashboard' : 'NGO dashboard'}>
      <div className="dashboard-landscape"/><div className="orbital orbital-one"/>
      <Sidebar role={authUser?.role === 'HOST' ? 'host' : 'ngo'} items={authUser?.role === 'HOST' ? [['home', 'Dashboard'], ['requests', 'Help Requests'], ['home', 'Accommodations'], ['settings', 'Settings']] : [['home', 'Dashboard'], ['home', 'Help Requests'], ['alert', 'SOS Queue'], ['bed', 'Shelters'], ['medical', 'Services'], ['megaphone', 'Alerts'], ['report', 'Reports'], ['settings', 'Settings']]}/>
      <div className="dashboard-main ngo-main"><div className="topbar"><span className="workspace-label">{t("PARTNER WORKSPACE")}</span><Profile name={authUser?.name || 'Partner'} initial={(authUser?.name || 'P').slice(0, 1).toUpperCase()}/></div><div className="welcome"><div><h2>{authUser?.role === 'HOST' ? t("Host Dashboard") : t("NGO Dashboard")}</h2><p>{t("Provide help. Make a difference.")}</p></div></div>
        <div className="stats-grid ngo-stats"><div className="stat"><span className="stat-icon violet"><Icon name="home" size={31}/></span><div><strong>{authUser?.role === 'HOST' ? apiAccommodations.length : apiShelters.length}</strong><small>{authUser?.role === 'HOST' ? t("Public stays") : t("Public shelters")}</small></div></div><div className="stat"><span className="stat-icon lime"><Icon name="people" size={31}/></span><div><strong>{requests.filter(request => request.accepted && !request.sos).length}</strong><small>{t("Accepted requests")}</small></div></div><div className="stat"><span className="stat-icon danger"><Icon name="alert" size={31}/></span><div><strong>{requests.filter(request => request.sos && !request.accepted).length}</strong><small>{t("Unclaimed SOS")}</small></div></div></div>
        <div className="ngo-middle"><div className="surface incoming"><div className="section-heading"><h3>{t("Incoming Help Requests")}</h3><button className="text-link" onClick={() => open('requests')}>{t("View all")}{' '}<Icon name="arrow" size={12}/></button></div><div className="request-list">{requests.length ? requests.map(request => <div className="request-row" key={`${request.sos ? 'sos' : 'request'}-${request.id}`}><span className={`request-icon ${request.urgent ? 'urgent' : ''}`}>{request.urgent ? t("SOS") : <Icon name={request.icon} size={28}/>}</span><div className="request-info"><strong>{request.title}{request.urgent && <i/>}</strong><small>{request.city} {' '}{t("·")}{' '}{request.status ? t(request.status) : request.time}</small></div><button className="outline-button" onClick={() => { setSelectedRequest(request); open('request-detail') }}>{t("View")}</button>{request.sos ? <button className={`accept-button ${request.accepted ? 'accepted' : ''}`} disabled={request.accepted} onClick={() => claimSos(request.id)}>{request.accepted ? t("Claimed") : t("Claim SOS")}</button> : request.status === 'Pending' ? <><button className="reject-button" onClick={() => updateRequest(request.id, 'reject')}>{t("Reject")}</button><button className="accept-button" onClick={() => accept(request.id)}>{t("Accept")}</button></> : request.status === 'Accepted' ? <button className="accept-button" onClick={() => updateRequest(request.id, 'complete')}>{t("Complete")}</button> : <span className="verified-tag">{t(request.status || 'Unknown')}</span>}</div>) : <p className="empty-state">{t("No incoming requests.")}</p>}</div></div>
          {authUser?.role === 'HOST' || authUser?.role === 'NGO' ? <form className="surface post-alert" onSubmit={createPartnerListing}><h3>{authUser.role === 'HOST' ? t("List accommodation") : t("List a shelter")}</h3><div className="modal-form"><label>{t("City")}<input required value={listingCity} onChange={event => setListingCity(event.target.value)}/></label><label>{t("Area")}<input required value={listingArea} onChange={event => setListingArea(event.target.value)}/></label><label>{t("Address")}{' '}<span>{t("(private until accepted)")}</span><input value={listingAddress} onChange={event => setListingAddress(event.target.value)}/></label><label>{authUser.role === 'HOST' ? t("Rooms available") : t("Beds available")}<input required min="1" type="number" value={listingCapacity} onChange={event => setListingCapacity(event.target.value)}/></label><button className="accept-button" type="submit" disabled={!authUser.verified}>{t("Submit for review")}</button>{!authUser.verified && <small>{t("Administrator verification is required before listing.")}</small>}</div></form> : null}
          {authUser?.role === 'NGO' && <>
            <form className="surface post-alert" onSubmit={createService}>
              <h3>{t("List a food or healthcare service")}</h3>
              <div className="modal-form">
                <label>{t("Service name")}<input required value={serviceName} onChange={event => setServiceName(event.target.value)}/></label>
                <label>{t("Category")}<select value={serviceCategory} onChange={event => setServiceCategory(event.target.value)}><option value="Food">{t("Food")}</option><option value="Healthcare">{t("Healthcare")}</option><option value="Medical">{t("Medical")}</option><option value="Legal">{t("Legal")}</option><option value="Transport">{t("Transport")}</option><option value="Other">{t("Other")}</option></select></label>
                <label>{t("City")}<input required value={serviceCity} onChange={event => setServiceCity(event.target.value)}/></label>
                <label>{t("Opening hours")}<input value={serviceHours} onChange={event => setServiceHours(event.target.value)}/></label>
                <label>{t("Contact")}<input value={serviceContact} onChange={event => setServiceContact(event.target.value)}/></label>
                <label>{t("Address")}<input value={serviceAddress} onChange={event => setServiceAddress(event.target.value)}/></label>
                <button className="accept-button" type="submit" disabled={!authUser.verified}>{t("Submit service for review")}</button>
              </div>
            </form>
            <form className="surface post-alert" onSubmit={postAlert}>
              <h3>{t("Post a community alert")}</h3>
              <div className="alert-hint"><Icon name="megaphone" size={23}/><p>{t("Share a typed, time-limited update.")}</p></div>
              <label>{t("Title")}<input required maxLength={200} value={alertTitle} onChange={event => setAlertTitle(event.target.value)}/></label>
              <label>{t("Message")}<textarea required maxLength={2000} value={alertText} onChange={event => setAlertText(event.target.value)} placeholder={t("Type your message...")}/></label>
              <label>{t("Type")}<select value={alertType} onChange={event => setAlertType(event.target.value)}><option value="Warning">{t("Warning")}</option><option value="Food">{t("Food")}</option><option value="Shelter">{t("Shelter")}</option><option value="Medical">{t("Medical")}</option></select></label>
              <label>{t("Expires at")}{' '}<span>{t("(optional)")}</span><input type="datetime-local" value={alertExpiresAt} onChange={event => setAlertExpiresAt(event.target.value)}/></label>
              <button className="accept-button" type="submit" disabled={!authUser.verified}>{t("Post alert")}</button>
              {!authUser.verified && <small>{t("Administrator verification is required to post alerts.")}</small>}
            </form>
          </>}
          {ownedListings.map(listing => <form className="surface post-alert" key={`${listing.listing_type}-${listing.id}`} onSubmit={event => updateOwnedListing(event, listing)}>
            <h3>{t("Edit")}{' '}{listing.listing_type}{t(":")}{' '}{listing.name || listing.area}</h3>
            <span className={listing.verified && !listing.blocked ? 'verified-tag' : 'pending-tag'}>{listing.blocked ? t("Blocked") : listing.closed ? t("Closed") : listing.verified ? t("Public") : t("Pending admin review")}</span>
            {listing.listing_type !== 'accommodation' && <label>{t("Name")}<input name="name" required defaultValue={listing.name}/></label>}
            {listing.listing_type === 'service' && <label>{t("Category")}<select name="category" defaultValue={listing.category}><option value="Food">{t("Food")}</option><option value="Healthcare">{t("Healthcare")}</option><option value="Medical">{t("Medical")}</option><option value="Legal">{t("Legal")}</option><option value="Transport">{t("Transport")}</option><option value="Other">{t("Other")}</option></select></label>}
            <label>{t("City")}<input name="city" required defaultValue={listing.city}/></label>
            {listing.listing_type !== 'service' && <label>{t("Area")}<input name="area" required defaultValue={listing.area}/></label>}
            <label>{t("Address")}<input name="address" defaultValue={listing.address}/></label>
            {listing.listing_type === 'shelter' && <><label>{t("Phone")}<input name="phone" defaultValue={listing.phone}/></label><label>{t("Beds available")}<input name="beds_available" required type="number" min="0" defaultValue={listing.beds_available}/></label><label><input name="women_safe" type="checkbox" defaultChecked={Boolean(listing.women_safe)}/> {' '}{t("Women-safe")}</label><label><input name="family_friendly" type="checkbox" defaultChecked={Boolean(listing.family_friendly)}/> {' '}{t("Family-friendly")}</label></>}
            {listing.listing_type === 'accommodation' && <><label>{t("Rooms")}<input name="rooms" required type="number" min="1" defaultValue={listing.rooms}/></label><label><input name="women_only" type="checkbox" defaultChecked={Boolean(listing.women_only)}/> {' '}{t("Women-only")}</label><label>{t("Description")}<textarea name="description" defaultValue={listing.description}/></label></>}
            {listing.listing_type === 'service' && <><label>{t("Opening hours")}<input name="opening_hours" defaultValue={listing.opening_hours}/></label><label>{t("Contact")}<input name="contact" defaultValue={listing.contact}/></label></>}
            <div className="button-row"><button className="accept-button" type="submit" disabled={!authUser?.verified}>{t("Save changes")}</button><button className="outline-button" type="button" onClick={() => changeListingStatus(listing)} disabled={!authUser?.verified}>{listing.closed ? t("Reopen listing") : t("Close listing")}</button></div>
          </form>)}
        </div>
        <div className="impact-banner ngo-banner"><div className="banner-art"><Icon name="people" size={64}/></div><div><h3>{t("Be the bridge in someone’s journey.")}</h3><p>{t("Your support makes a difference.")}</p></div><button className="outline-button" onClick={() => open('about')}>{t("Learn More")}{' '}<Icon name="arrow" size={12}/></button></div>
      </div>
    </section>

    <section className="panel dashboard blue" hidden={view !== 'admin'} aria-label={t("Admin dashboard")}>
      <div className="dashboard-landscape"/><div className="orbital orbital-one"/>
      <Sidebar role="admin" active="Verification" items={[['home', 'Dashboard'], ['shield', 'Verification'], ['report', 'Reports'], ['requests', 'Audit Log'], ['settings', 'Settings']]}/>
      <div className="dashboard-main admin-main"><div className="topbar"><span className="workspace-label">{t("TRUST & SAFETY")}</span><Profile name={authUser?.name || 'Administrator'} initial={(authUser?.name || 'A').slice(0, 1).toUpperCase()}/></div><div className="welcome"><div><h2>{t("Admin Panel")}</h2><p>{t("Verify. Monitor. Ensure Safety.")}</p></div><Icon name="shield" size={85} className="admin-shield"/></div>
        <div className="admin-middle"><div className="verification-section"><div className="tabs" role="tablist" aria-label={t("Admin lists")}>{['Pending Verifications', 'Pending Listings', 'Reports', 'Blocked Listings', 'Failed Notifications', 'SOS'].map(tab => {
          const count = tab === 'Pending Verifications' ? verifications.length : tab === 'Pending Listings' ? pendingListings.length : tab === 'Reports' ? adminReports.length : tab === 'Blocked Listings' ? blockedListings.length : tab === 'Failed Notifications' ? failedNotifications.length : adminSos.length
          return <button key={tab} role="tab" aria-selected={adminTab === tab} onClick={() => setAdminTab(tab)} className={adminTab === tab ? 'selected' : ''}>{t(tab)} {' '}{t("(")}{count}{t(")")}</button>
        })}</div><div className="surface verification-list">{adminTab === 'Pending Verifications' ? verifications.length ? verifications.map(org => <div className="verification-row" key={org.id}><span className="org-icon"><Icon name="user" size={27}/></span><div className="org-info"><strong>{org.name}</strong><small>{t(org.role)} {t(org.verification_status || "Submitted")} {org.time}</small></div><button className="outline-button" onClick={() => { setSelectedOrg(org.name); setSelectedOrgId(org.id); setVerificationNotes(org.verification_review_notes || ''); setVerificationExpiresAt(localDateTimeInput(org.verification_expires_at || null)); open('verification') }}>{t("View")}</button><button className="approve-button" onClick={() => decide(org.id, true)}>{t("Approve")}</button><button className="reject-button" onClick={() => decide(org.id, false)}>{t("Reject")}</button></div>) : <div className="empty-state">{t("No pending partner verifications.")}</div>
          : adminTab === 'Pending Listings' ? pendingListings.length ? pendingListings.map(listing => <div className="verification-row" key={`${listing.listing_type}-${listing.id}`}><div className="org-info"><strong>{listing.label}</strong><small>{listing.listing_type} {' '}{t("· Submitted by")}{' '}{listing.owner_name}</small></div><button className="approve-button" onClick={() => moderateListing(listing, 'approve')}>{t("Approve")}</button><button className="reject-button" onClick={() => moderateListing(listing, 'block')}>{t("Block")}</button></div>) : <div className="empty-state">{t("No listings awaiting review.")}</div>
          : adminTab === 'Reports' ? adminReports.length ? adminReports.map(report => <div className="verification-row" key={report.id}><div className="org-info"><strong>{report.listing_type} {' '}{t("#")}{report.listing_id}</strong><small>{report.reason}</small></div><button className="approve-button" onClick={() => decideReport(report.id, 'block')}>{t("Block listing")}</button><button className="outline-button" onClick={() => decideReport(report.id, 'dismiss')}>{t("Dismiss")}</button></div>) : <div className="empty-state">{t("No open reports.")}</div>
          : adminTab === 'Blocked Listings' ? blockedListings.length ? blockedListings.map(listing => <div className="verification-row" key={`${listing.listing_type}-${listing.id}`}><div className="org-info"><strong>{listing.label}</strong><small>{listing.listing_type} {' '}{t("·")}{' '}{listing.owner_name}</small></div><button className="outline-button" onClick={() => moderateListing(listing, 'unblock')}>{t("Unblock")}</button></div>) : <div className="empty-state">{t("No blocked listings.")}</div>
          : adminTab === 'Failed Notifications' ? failedNotifications.length ? failedNotifications.map(item => <div className="verification-row" key={item.id}><div className="org-info"><strong>{t(item.channel)} {' '}{t("·")}{' '}{t(item.status || 'Unknown')}</strong><small>{t("SOS request #")}{item.request_id} {' '}{t("·")}{' '}{t("Attempts")}{t(":")} {formatNumber(item.attempt_count)} {' '}{t("·")}{' '}{formatDate(item.updated_at, true)}{item.last_error_code && <> {' '}{t("·")}{' '}{item.last_error_code}</>}</small></div><button className="outline-button" onClick={() => retryNotification(item.id)}>{t("Retry")}</button></div>) : <div className="empty-state">{t("No failed emergency notifications.")}</div> : adminSos.length ? adminSos.map(item => <div className="verification-row" key={item.id}><div className="org-info"><strong>{t("Emergency request #")}{item.id}</strong><small>{t(item.status || 'Unknown')} {' '}{t("·")}{' '}{item.time}</small></div><button className="outline-button" onClick={() => open('sos-queue')}>{t("Monitor queue")}</button></div>) : <div className="empty-state">{t("No unresolved SOS requests.")}</div>}</div></div><div className="surface activity"><div className="section-heading"><h3>{t("Recent Activity")}</h3><button className="text-link" onClick={() => open('audit')}>{t("View all")}{' '}<Icon name="arrow" size={11}/></button></div>{auditEntries.length ? auditEntries.slice(0, 5).map((entry, index) => <p className="audit-row" key={`${entry.action}-${entry.target_id}-${index}`}>{entry.action} {' '}{t("·")}{' '}{entry.target_type || t("system")} {entry.target_id ? `#${entry.target_id}` : ''}</p>) : <p className="empty-state">{t("No administrative activity recorded.")}</p>}</div></div>
        <section className="surface analytics-panel" aria-label={t("Platform analytics")}>
          <div className="analytics-heading"><div><h3>{t("Platform Analytics")}</h3><p>{t("Live counts for users, requests, listings, and SOS.")}</p></div><button className="outline-button" disabled={adminAnalytics.status === 'loading'} onClick={loadAdminAnalytics}>{t("Refresh")}</button></div>
          {renderAdminAnalytics()}
        </section>
      </div>
    </section>

    {toast && <div className="toast" role="status"><span className="status-check"><Icon name="check" size={13}/></span>{toast}<button aria-label={t("Dismiss notification")} onClick={() => setToast('')}><Icon name="close" size={16}/></button></div>}
    {modal && <div className="modal-backdrop" onClick={() => setModal(null)}><section className={`modal ${modal === 'sos' ? 'emergency-modal' : ''}`} role="dialog" aria-modal="true" aria-labelledby="modal-title" ref={modalRef} tabIndex={-1} onClick={event => event.stopPropagation()}><button className="modal-close" aria-label={t("Close dialog")} onClick={() => setModal(null)}><Icon name="close" size={21}/></button><div className="modal-brand"><Logo label={t('WarBridge')}/><span>{t("WARBRIDGE")}</span></div>
      {modal === 'shelters' && <><h2 id="modal-title">{t("Find a safe place.")}</h2><p className="modal-intro">{t("Verified spaces. Real people ready to help.")}</p><div className="filters"><label><Icon name="search" size={16}/><input placeholder={t("Search by city...")} value={city} onChange={event => setCity(event.target.value)}/></label><button className={womenOnly ? 'filter active-filter' : 'filter'} onClick={() => setWomenOnly(!womenOnly)}><Icon name="shield" size={15}/> {' '}{t("Women-safe")}</button></div><div className="listing-list">{apiShelters.filter(s => s.city.toLowerCase().includes(city.toLowerCase()) && (!womenOnly || s.women_safe)).map(s => <article className="listing" key={s.id}><div className="listing-top"><span className="verified-tag"><Icon name="shield" size={13}/> {' '}{t("Verified NGO")}</span><span className="rating"><Icon name="star" size={12}/> {Number(s.rating).toFixed(1)} {' '}{t("(")}{s.rating_count}{t(")")}</span></div><h3>{s.name}</h3><p><Icon name="pin" size={13}/> {s.area}{t(",")}{' '}{s.city}</p><div className="listing-bottom"><span><b>{s.beds_available} {' '}{t("beds available")}</b>{Boolean(s.women_safe) && ' · Women-safe'}</span><button className="primary purple-button" disabled={requested.includes(s.name)} onClick={() => {
        void api.post('/api/requests', { shelter_id: s.id })
          .then(() => { setRequested(items => [...items, s.name]); notify('Help request submitted for review.') })
          .catch(error => notify(error instanceof Error ? error.message : 'Sign in as a Displaced user before requesting help.'))
      }}>{requested.includes(s.name) ? t("Requested") : t("Request help")}<Icon name="arrow" size={13}/></button></div><small>{t("Exact address is shared only after acceptance. Listing updated")}{' '}{formatDate(s.updated_at, true)}{t(".")}</small></article>)}{apiShelters.filter(s => s.city.toLowerCase().includes(city.toLowerCase()) && (!womenOnly || s.women_safe)).length === 0 && <p className="empty-state">{t("No verified shelters are currently listed.")}</p>}</div></>}
      {modal === 'accommodations' && <><h2 id="modal-title">{t("Host stays")}</h2><p className="modal-intro">{t("Only administrator-approved stays with available rooms are shown. Addresses stay private until a host accepts your request.")}</p><div className="filters"><label><Icon name="search" size={16}/><input placeholder={t("Search by city...")} value={city} onChange={event => setCity(event.target.value)}/></label></div><div className="listing-list">{apiAccommodations.filter(item => item.city.toLowerCase().includes(city.toLowerCase()) && (!womenOnly || item.women_only)).map(item => <article className="listing" key={item.id}><span className="verified-tag"><Icon name="shield" size={13}/> {' '}{t("Verified host")}</span><h3>{item.area}{t(",")}{' '}{item.city}</h3><p>{formatNumber(item.rooms_available)} {' '}{t("rooms available")}{Boolean(item.women_only) ? t(" · Women-only") : ''}</p>{item.description && <p>{item.description}</p>}<button className="primary purple-button" disabled={requested.includes(`accommodation-${item.id}`)} onClick={() => { void api.post('/api/requests', { type: 'accommodation', accommodation_id: item.id }).then(() => { setRequested(items => [...items, `accommodation-${item.id}`]); if (authUser) loadRoleData(authUser); notify('Help request submitted for review.') }).catch(error => notify(error instanceof Error ? error.message : 'Sign in as a displaced person before requesting a stay.')) }}>{t("Request stay")}{' '}<Icon name="arrow" size={13}/></button><small>{t("Updated")}{' '}{formatDate(item.updated_at, true)}</small></article>)}{apiAccommodations.filter(item => item.city.toLowerCase().includes(city.toLowerCase()) && (!womenOnly || item.women_only)).length === 0 && <p className="empty-state">{t("No verified host stays are currently available.")}</p>}</div></>}
      {modal === 'sos' && <><div className="emergency-heading"><Icon name="alert" size={30}/><h2 id="modal-title">{t("Emergency SOS")}</h2></div><p className="emergency-warning">{t("In immediate danger? Call")}{' '}<a href="tel:112">{t("112")}</a> {' '}{t("now.")}<br/>{t("WarBridge cannot guarantee an emergency response.")}</p><p className="modal-intro">{t("Submitting SOS creates a rate-limited request for a verified NGO. It does not replace emergency services.")}</p><form className="modal-form" onSubmit={event => {
        event.preventDefault()
        const form = new FormData(event.currentTarget)
        void api.post('/api/sos', { name: form.get('name'), phone: form.get('phone'), location: form.get('location'), website: form.get('website') })
          .then(() => { setModal(null); notify('SOS submitted to the NGO queue.') })
          .catch(error => notify(error instanceof Error ? error.message : 'SOS could not be submitted.'))
      }}><label>{t("Name")}{' '}<span>{t("(optional)")}</span><input name="name" placeholder={t("How should we address you?")}/></label><label>{t("Phone")}{' '}<span>{t("(optional)")}</span><input name="phone" type="tel" placeholder={t("A number an NGO can reach you on")}/></label><label>{t("Your location")}{' '}<span>{t("(optional)")}</span><textarea name="location" placeholder={t("City, area or nearby landmark. Do not share sensitive details.")}/></label><input className="sr-only" name="website" tabIndex={-1} autoComplete="off" aria-hidden="true"/><button className="accept-button" type="submit"><Icon name="alert" size={18}/> {' '}{t("Send SOS")}</button></form></>}
      {modal === 'alerts' && <><h2 id="modal-title">{t("Community alerts")}</h2><p className="modal-intro">{t("Current updates published by verified partners.")}</p><div className="listing-list">{alerts.length ? alerts.map(alert => <article className="listing alert-listing" key={alert.id}><span className="alert-circle"><Icon name="megaphone"/></span><div><span className="verified-tag">{alert.type} {' '}{t("·")}{' '}{alert.partner_name}</span><h3>{alert.title}</h3><p>{alert.message}</p><small>{alert.expires_at ? t('Expires {date}', { date: formatDate(alert.expires_at, true) }) : t("No expiry set")}</small></div></article>) : <p className="empty-state">{t("There are no current community alerts.")}</p>}</div>
        {authUser?.role === 'NGO' && <><h3>{t("Your alerts")}</h3>{managedAlerts.length ? managedAlerts.map(alert => <form className="listing" key={alert.id} onSubmit={event => updateAlert(event, alert)}>
          <span className={alert.archived ? 'pending-tag' : 'verified-tag'}>{alert.archived ? t("Archived") : t(alert.type)}</span>
          <label>{t("Title")}<input name="title" required maxLength={200} defaultValue={alert.title} disabled={Boolean(alert.archived)}/></label>
          <label>{t("Message")}<textarea name="message" required maxLength={2000} defaultValue={alert.message} disabled={Boolean(alert.archived)}/></label>
          <label>{t("Type")}<select name="type" defaultValue={alert.type} disabled={Boolean(alert.archived)}><option value="Warning">{t("Warning")}</option><option value="Food">{t("Food")}</option><option value="Shelter">{t("Shelter")}</option><option value="Medical">{t("Medical")}</option></select></label>
          <label>{t("Expires at")}{' '}<span>{t("(optional)")}</span><input name="expires_at" type="datetime-local" defaultValue={localDateTimeInput(alert.expires_at)} disabled={Boolean(alert.archived)}/></label>
          <div className="button-row"><button className="accept-button" type="submit" disabled={Boolean(alert.archived) || !authUser.verified}>{t("Save alert")}</button><button className="reject-button" type="button" onClick={() => archiveAlert(alert)} disabled={Boolean(alert.archived) || !authUser.verified}>{t("Archive")}</button></div>
        </form>) : <p className="empty-state">{t("You have not posted any alerts.")}</p>}</>}
      </>}
      {modal === 'services' && <><h2 id="modal-title">{t("Everyday essentials.")}</h2><p className="modal-intro">{t("Services listed by verified community partners.")}</p>{apiServices.length ? apiServices.map(service => <article className="listing service-listing" key={service.id}><Icon name="people" size={30}/><div><span className="verified-tag">{service.category} {' '}{t("· Verified service")}</span><h3>{service.name}</h3><p>{service.city}</p><small>{service.opening_hours || t("Hours not provided")}</small></div></article>) : <p className="empty-state">{t("No verified services are currently listed.")}</p>}</>}
      {modal === 'helplines' && <><h2 id="modal-title">{t("You don’t have to face it alone.")}</h2><p className="modal-intro">{t("India emergency helplines. Tap a number to call directly.")}</p><Helplines full/><p className="privacy-note"><Icon name="shield" size={17}/> {' '}{t("In an emergency, call a helpline first. WarBridge is a coordination tool, not an emergency service.")}</p></>}
      {modal === 'requests' && <><h2 id="modal-title">{t("Help requests")}</h2><p className="modal-intro">{t("Requests are shown only to the account that owns them or is authorized to handle them.")}</p>{(authUser?.role === 'NGO' ? requests.filter(item => !item.sos) : requests).length ? (authUser?.role === 'NGO' ? requests.filter(item => !item.sos) : requests).map(r => <article className="listing request-modal-row" key={r.id}><div><span className={r.status === 'Accepted' || r.status === 'Completed' ? 'verified-tag' : 'pending-tag'}>{t(r.status || "Unknown")}</span><h3>{r.title}</h3><p>{r.city} {' '}{t("·")}{' '}{r.time}</p></div><div className="button-row"><button className="outline-button" onClick={() => { setSelectedRequest(r); open('request-detail') }}>{t("View details")}</button>{authUser?.role === 'DISPLACED' && !r.sos && ['Pending', 'Accepted'].includes(r.status || '') && <button className="reject-button" onClick={() => updateRequest(r.id, 'cancel')}>{t("Cancel request")}</button>}</div></article>) : <p className="empty-state">{t("No help requests are available for this account.")}</p>}</>}
      {modal === 'request-detail' && selectedRequest && <><h2 id="modal-title">{selectedRequest.title}</h2><p className="modal-intro">{selectedRequest.city} {' '}{t("·")}{' '}{selectedRequest.time}</p>{selectedRequest.sos ? <><article className="listing"><span className="pending-tag">{t("SOS ·")}{' '}{t(selectedRequest.status || 'Unknown')}</span><h3>{selectedRequest.requester_name || (selectedRequest.accepted ? t("Caller details") : t("Caller details are private"))}</h3>{selectedRequest.accepted ? <><p>{t("Contact:")}{' '}{selectedRequest.contact ? formatPhone(selectedRequest.contact) : t("Not provided")}</p><p>{t("Location:")}{' '}{selectedRequest.location_text || t("Not provided")}</p></> : <p>{t("Contact and precise location remain hidden until a verified NGO claims this SOS or it is escalated to an administrator.")}</p>}<small>{t("WarBridge does not contact emergency services. Call 112 when appropriate.")}</small></article>{authUser?.role === 'ADMIN' && selectedRequest.status === 'Escalated' ? <button className="accept-button" onClick={() => updateSos(selectedRequest.id, 'resolve')}>{t("Resolve escalation")}</button> : selectedRequest.accepted && authUser?.role === 'NGO' ? <div className="button-row">{selectedRequest.status === 'Accepted' && <button className="outline-button" onClick={() => updateSos(selectedRequest.id, 'escalate')}>{t("Escalate to admin")}</button>}<button className="accept-button" onClick={() => updateSos(selectedRequest.id, 'resolve')}>{t("Resolve SOS")}</button></div> : authUser?.role === 'NGO' && <button className="accept-button" onClick={() => { claimSos(selectedRequest.id); setModal(null) }}>{t("Claim SOS")}</button>}</> : <><article className="listing"><span className={selectedRequest.status === 'Accepted' || selectedRequest.status === 'Completed' ? 'verified-tag' : 'pending-tag'}>{t("Request ·")}{' '}{t(selectedRequest.status || "Unknown")}</span><h3>{selectedRequest.status === 'Accepted' ? t("A partner accepted this request") : selectedRequest.status === 'Completed' ? t("This request is complete") : selectedRequest.status === 'Rejected' ? t("This request was rejected") : selectedRequest.status === 'Cancelled' ? t("This request was cancelled") : t("A person is looking for support")}</h3><p>{selectedRequest.status === 'Pending' ? t("Review the request and confirm capacity before accepting. Contact details remain private until permitted.") : t("The request status is shown above. No further action is available in this state.")}</p><small>{t("All access decisions must be made by a verified human.")}</small></article>{(authUser?.role === 'NGO' || authUser?.role === 'HOST') && selectedRequest.status === 'Pending' ? <div className="button-row"><button className="reject-button" onClick={() => updateRequest(selectedRequest.id, 'reject')}>{t("Reject request")}</button><button className="primary" onClick={() => { accept(selectedRequest.id); setModal(null) }}>{t("Accept request")}{' '}<Icon name="check" size={16}/></button></div> : (authUser?.role === 'NGO' || authUser?.role === 'HOST') && selectedRequest.status === 'Accepted' ? <button className="accept-button" onClick={() => updateRequest(selectedRequest.id, 'complete')}>{t("Mark completed")}</button> : authUser?.role === 'DISPLACED' && ['Pending', 'Accepted'].includes(selectedRequest.status || '') ? <button className="reject-button" onClick={() => updateRequest(selectedRequest.id, 'cancel')}>{t("Cancel request")}</button> : null}</>}</>}
      {modal === 'sos-queue' && <><h2 id="modal-title">{authUser?.role === 'ADMIN' ? t("SOS monitoring") : t("Verified NGO SOS queue")}</h2><p className="modal-intro">{t("Unclaimed SOS requests remain private. Escalated records show caller details to administrators and verified assigned NGOs.")}</p>{(authUser?.role === 'ADMIN' ? adminSos : requests.filter(request => request.sos)).length ? (authUser?.role === 'ADMIN' ? adminSos : requests.filter(request => request.sos)).map(item => <article className="listing request-modal-row" key={`sos-${item.id}`}><div><span className="pending-tag">{t(item.status || 'Unknown')}</span><h3>{item.title}</h3><p>{item.time}</p><small>{item.city}</small></div>{((authUser?.role === 'NGO') || (authUser?.role === 'ADMIN' && item.status === 'Escalated')) && <button className="outline-button" onClick={() => { setSelectedRequest(item); open('request-detail') }}>{item.accepted ? t("View details") : t("View / claim")}</button>}</article>) : <p className="empty-state">{t("No unresolved SOS requests.")}</p>}</>}
      {modal === 'verification' && <>
        <h2 id="modal-title">{t('Partner verification')}</h2>
        <p className="modal-intro">{t('Review a partner before granting access to sensitive actions.')}</p>
        <article className="listing">
          <span className="pending-tag">{t(selectedOrgId ? verifications.find(org => org.id === selectedOrgId)?.verification_status || 'Submitted' : 'Submitted')}</span>
          <h3>{selectedOrg}</h3>
          <p>{t('WarBridge does not collect or validate identity documents. Confirm registration, references and contacts through your approved secure process before deciding.')}</p>
          <p className="privacy-note">{t('Verification decisions are recorded in the audit history. Approval here records a manual administrator decision, not an identity-provider check.')}</p>
          {selectedOrgId && verifications.find(org => org.id === selectedOrgId)?.verification_review_notes && <p>{t('Admin review notes')}{t(':')} {verifications.find(org => org.id === selectedOrgId)?.verification_review_notes}</p>}
        </article>
        <div className="modal-form">
          <label>{t('Admin review notes')}<textarea value={verificationNotes} onChange={event => setVerificationNotes(event.target.value)} maxLength={1000} placeholder={t('Enter manual review notes.')}/></label>
          <label>{t('Verification expiry (optional)')}<input type="datetime-local" value={verificationExpiresAt} onChange={event => setVerificationExpiresAt(event.target.value)}/></label>
        </div>
        <div className="button-row">
          <button className="outline-button" disabled={!selectedOrgId} onClick={() => selectedOrgId && startVerificationReview(selectedOrgId)}>{t('Mark under review')}</button>
          <button className="approve-button" disabled={!selectedOrgId} onClick={() => selectedOrgId && decide(selectedOrgId, true, verificationNotes, verificationExpiresAt)}>{t('Approve partner')}</button>
          <button className="reject-button" disabled={!selectedOrgId} onClick={() => selectedOrgId && decide(selectedOrgId, false, verificationNotes)}>{t('Reject')}</button>
        </div>
      </>}
      {modal === 'signin' && <>
        <h2 id="modal-title">{authMode === 'signin' ? t("Sign in to WarBridge") : `Register ${authRole === 'DISPLACED' ? 'as a displaced person' : authRole === 'HOST' ? 'as a host' : 'your NGO'}`}</h2>
        <p className="modal-intro">{authMode === 'signin' ? t("Choose your account type and sign in with your registered name or email.") : t("Partner accounts require administrator verification before they can publish listings or handle requests.")}</p>
        {authMode === 'signin' ? <div className="tabs auth-tabs" role="tablist" aria-label={t("Account type")}>{(['DISPLACED', 'HOST', 'NGO', 'ADMIN'] as AuthRole[]).map(role => <button key={role} type="button" role="tab" aria-selected={authRole === role} className={authRole === role ? 'selected' : ''} onClick={() => { setAuthRole(role); setAuthError('') }}>{role === 'DISPLACED' ? t("Displaced") : role === 'HOST' ? t("Host") : role === 'ADMIN' ? t("Administrator") : t("NGO")}</button>)}</div> : <div className="tabs auth-tabs"><button type="button" className="selected" disabled>{authRole === 'DISPLACED' ? t("Displaced registration") : authRole === 'HOST' ? t("Host registration") : t("NGO registration")}</button></div>}
        <form className="modal-form" onSubmit={authMode === 'signin' ? signIn : registerAccount}>
          <label>{authRole === 'NGO' ? t("NGO name or email") : authRole === 'HOST' ? t("Host name or email") : authRole === 'ADMIN' ? t("Administrator username or email") : t("Name or email")}<input required autoComplete="username" value={authIdentity} onChange={event => setAuthIdentity(event.target.value)} placeholder={authRole === 'ADMIN' ? 'Enter your admin username' : 'Enter your registered name'}/></label>
          {authMode === 'register' && <label>{t("Contact email")}<input required type="email" autoComplete="email" value={authEmail} onChange={event => setAuthEmail(event.target.value)} placeholder={t("name@example.org")}/></label>}
          {authMode === 'register' && authRole === 'DISPLACED' && <label>{t("Gender")}{' '}<span>{t("(optional; used only for eligibility filters)")}</span><select value={authGender} onChange={event => setAuthGender(event.target.value)}><option value="">{t("Prefer not to say")}</option><option value="female">{t("Female")}</option><option value="male">{t("Male")}</option><option value="other">{t("Another identity")}</option></select></label>}
          <label>{t("Password")}<input required minLength={authMode === 'register' ? 8 : undefined} type="password" autoComplete={authMode === 'register' ? 'new-password' : 'current-password'} value={authPassword} onChange={event => setAuthPassword(event.target.value)} placeholder={authMode === 'register' ? 'At least 8 characters' : 'Enter your password'}/></label>
          {authError && <p className="form-error" role="alert">{authError}</p>}
          <button className="primary purple-button" type="submit" disabled={authBusy}>{authBusy ? t("Please wait…") : authMode === 'signin' ? t("Sign in") : t("Create account")} <Icon name="arrow" size={16}/></button>
        </form>
        {authRole !== 'ADMIN' && <button className="text-link" onClick={() => { setAuthMode(authMode === 'signin' ? 'register' : 'signin'); setAuthError('') }}>{authMode === 'signin' ? t("Create an account") : t("Already registered? Sign in")}</button>}
        {authMode === 'signin' && <button className="text-link" onClick={() => { setAuthRole('DISPLACED'); setAuthError('') }}>{t("Continue as a displaced person")}</button>}
      </>}
      {modal === 'ratings' && <><h2 id="modal-title">{t("Share your experience.")}</h2><p className="modal-intro">{t("Rate a shelter or host stay after your help request is marked complete.")}</p>{requests.filter(item => item.status === 'Completed' && item.listing_type && item.listing_id).length ? requests.filter(item => item.status === 'Completed' && item.listing_type && item.listing_id).map(item => {
        const existing = ratings.find(rating => rating.listing_type === item.listing_type && rating.listing_id === item.listing_id)
        return <form className="listing" key={`${item.listing_type}-${item.listing_id}`} onSubmit={event => submitRating(event, item)}>
          <h3>{item.title} {' '}{t("·")}{' '}{item.city}</h3>
          <label>{t("Rating")}<select name="stars" defaultValue={existing?.stars || 5}><option value="5">{t("5 — Excellent")}</option><option value="4">{t("4 — Good")}</option><option value="3">{t("3 — Okay")}</option><option value="2">{t("2 — Poor")}</option><option value="1">{t("1 — Very poor")}</option></select></label>
          <label>{t("Comment")}<textarea name="comment" maxLength={1000} defaultValue={existing?.comment || ''} placeholder={t("Share an optional note")}/></label>
          <button className="accept-button" type="submit">{existing ? t("Update rating") : t("Submit rating")}</button>
        </form>
      }) : <p className="empty-state">{t("Completed stays eligible for rating will appear here.")}</p>}</>}
      {modal === 'reports' && <><h2 id="modal-title">{t("Help keep the community safe.")}</h2><p className="modal-intro">{t("Report a suspicious or unsafe listing for administrator review.")}</p><form className="modal-form" onSubmit={event => {
        event.preventDefault()
        const form = new FormData(event.currentTarget)
        const listingId = Number(form.get('listing_id'))
        void api.post('/api/reports', {
          listing_type: form.get('listing_type'),
          listing_id: listingId,
          reason: form.get('reason'),
        }).then(() => { notify('Your report was submitted.'); setModal(null) })
          .catch(error => notify(error instanceof Error ? error.message : 'Sign in before submitting a report.'))
      }}><label>{t("Listing type")}<select name="listing_type"><option value="shelter">{t("Shelter")}</option><option value="accommodation">{t("Accommodation")}</option><option value="service">{t("Service")}</option></select></label><label>{t("Listing ID")}<input required name="listing_id" type="number" min="1" step="1" placeholder={t("ID shown on the listing")}/></label><label>{t("What happened?")}<textarea required name="reason" minLength={5} placeholder={t("Describe your concern (at least 5 characters)")}/></label><button className="primary" type="submit">{t("Submit report")}{' '}<Icon name="arrow" size={16}/></button></form></>}
      {modal === 'audit' && <><h2 id="modal-title">{t("Trust & safety activity")}</h2><p className="modal-intro">{t("Administrative actions are recorded in the audit history.")}</p>{auditEntries.length ? auditEntries.map((entry, index) => <article className="listing" key={`${entry.action}-${entry.target_id}-${index}`}><strong>{entry.action}</strong><p>{entry.target_type || t("system")} {entry.target_id ? `#${entry.target_id}` : ''}</p><small>{formatDate(entry.created_at, true)}</small></article>) : <p className="empty-state">{t("No administrative activity recorded.")}</p>}</>}
      {modal === 'settings' && <><h2 id="modal-title">{t("Account settings")}</h2><p className="modal-intro">{t("WarBridge brings communities together through verified human support.")}</p><article className="listing"><h3>{t("Region")}</h3><p>{t("India · Emergency numbers 112, 181 and 1098")}</p><h3>{t("Language")}</h3><p>{t("English")}</p><h3>{t("Account")}</h3><p>{authUser ? `${authUser.name} · ${authUser.role}` : t("Public access")}</p></article>{authUser && <button className="outline-button" onClick={() => {
        void api.post('/api/auth/logout').then(() => api.resetCsrf()).then(() => {
          setAuthUser(null)
          setView('home')
          setModal(null)
          notify('You have signed out.')
        }).catch(error => notify(error instanceof Error ? error.message : 'Could not sign out.'))
      }}><Icon name="logout" size={15}/> {' '}{t("Sign out")}</button>}</>}
      {(modal === 'about' || modal === 'donate') && <><h2 id="modal-title">{modal === 'donate' ? t("Together, we can rebuild.") : t("A bridge. Never a gatekeeper.")}</h2><p className="modal-intro">{t("WarBridge connects people in need with shelters, food, healthcare and verified humans who can help.")}</p><div className="about-values"><div><Icon name="shield" size={26}/><h3>{t("Safety comes first")}</h3><p>{t("Exact addresses stay private until a request is accepted by a verified partner.")}</p></div><div><Icon name="people" size={26}/><h3>{t("People make decisions")}</h3><p>{t("NGOs, hosts and shelters make every access decision. The app helps coordinate.")}</p></div><div><Icon name="heart" size={26}/><h3>{t("Help without barriers")}</h3><p>{t("Emergency helplines and verified public resources are available without an account.")}</p></div></div><div className="privacy-note">{t("For immediate help in India, call 112.")}</div></>}
    </section></div>}
  </main></div>
}
