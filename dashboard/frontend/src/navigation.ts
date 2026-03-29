export type NavItem = {
  label: string
  to: string
  public: boolean
  inMoreMenu?: boolean
  mobileLabel?: string
}

const NAV_ITEMS: NavItem[] = [
  { label: 'Overview', to: '/', public: true },
  { label: 'Dashboard', to: '/dashboard', public: false },
  { label: 'Universe', to: '/universe', public: true },
  { label: 'Portfolio', to: '/portfolio', public: true },
  { label: 'Runs', to: '/runs', public: true, mobileLabel: 'Run History' },
  { label: 'World News', to: '/world-news', public: true },
  { label: 'Roadmap', to: '/roadmap', public: true },
  { label: 'Opportunity', to: '/opportunity', public: true, inMoreMenu: true },
  { label: 'Order Mgmt', to: '/orders', public: true, inMoreMenu: true },
  { label: 'Chat', to: '/chat', public: true, inMoreMenu: true },
  { label: 'Evolution', to: '/evolution', public: true, inMoreMenu: true },
  { label: 'Costs', to: '/costs', public: true, inMoreMenu: true },
]

export function getNavigationItems(authenticated: boolean) {
  return NAV_ITEMS.filter((item) => {
    if (!authenticated) return item.public
    return item.to !== '/'
  })
}

export function getPrimaryNavigationItems(authenticated: boolean) {
  return getNavigationItems(authenticated).filter((item) => !item.inMoreMenu)
}

export function getMoreNavigationItems(authenticated: boolean) {
  return getNavigationItems(authenticated).filter((item) => item.inMoreMenu)
}
