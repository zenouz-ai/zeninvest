import { useCallback, useEffect, useState } from 'react'
import {
  learningApi,
  type LearningEvaluationSummary,
  type LearningPageStatus,
  type LearningRunSummary,
  type NorthStarMetrics,
} from '../../../api/client'

export type LearningTabId = 'shadow' | 'evaluation' | 'attribution' | 'rejection'

export interface LearningPageData {
  loading: boolean
  error: string | null
  status: LearningPageStatus | null
  northStar: NorthStarMetrics | null
  evaluation: LearningEvaluationSummary | null
  runs: LearningRunSummary[]
  activeTab: LearningTabId
  setActiveTab: (tab: LearningTabId) => void
  refresh: () => void
}

export function useLearningPageData(): LearningPageData {
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<LearningPageStatus | null>(null)
  const [northStar, setNorthStar] = useState<NorthStarMetrics | null>(null)
  const [evaluation, setEvaluation] = useState<LearningEvaluationSummary | null>(null)
  const [runs, setRuns] = useState<LearningRunSummary[]>([])
  const [activeTab, setActiveTab] = useState<LearningTabId>('shadow')

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [pageStatus, runsResp] = await Promise.all([
        learningApi.getStatus(),
        learningApi.listRuns(25),
      ])
      setStatus(pageStatus)
      setNorthStar(pageStatus.north_star)
      setEvaluation(pageStatus.latest_evaluation)
      setRuns(runsResp.runs)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load learning page')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  return {
    loading,
    error,
    status,
    northStar,
    evaluation,
    runs,
    activeTab,
    setActiveTab,
    refresh: load,
  }
}
