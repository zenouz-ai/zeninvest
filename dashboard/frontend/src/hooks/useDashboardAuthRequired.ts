import { useSyncExternalStore } from 'react'
import {
  getDashboardAuthRequired,
  subscribeDashboardAuth,
} from '../utils/authErrorBridge'

export function useDashboardAuthRequired(): boolean {
  return useSyncExternalStore(subscribeDashboardAuth, getDashboardAuthRequired, getDashboardAuthRequired)
}
