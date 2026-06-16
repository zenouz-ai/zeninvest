import { Link } from 'react-router-dom'
import { PageBrandHeader } from '../components/PageBrandHeader'
import { SkeletonCard } from '../components/Skeleton'
import { Panel } from '../components/Panel'
import { ArtifactFreshnessBanner } from '../components/learning/ArtifactFreshnessBanner'
import { LearningNorthStarHero } from '../components/learning/LearningNorthStarHero'
import { LearningTabs } from '../components/learning/LearningTabs'
import { PromotionGateStrip } from '../components/learning/PromotionGateStrip'
import { useLearningPageData } from '../components/learning/hooks/useLearningPageData'
import { AttributionPanel } from '../components/learning/panels/AttributionPanel'
import { DataLabAccordion } from '../components/learning/panels/DataLabAccordion'
import { EvaluationPanel } from '../components/learning/panels/EvaluationPanel'
import { ModelLabPanel } from '../components/learning/panels/ModelLabPanel'
import { RejectionQualityPanel } from '../components/learning/panels/RejectionQualityPanel'
import { ShadowPanel } from '../components/learning/panels/ShadowPanel'

export default function LearningInsights() {
  const {
    loading,
    error,
    status,
    northStar,
    evaluation,
    runs,
    activeTab,
    setActiveTab,
  } = useLearningPageData()

  if (loading) return <SkeletonCard lines={12} data-testid="learning-loading" />

  if (error) {
    return (
      <Panel>
        <p className="text-loss text-sm">{error}</p>
      </Panel>
    )
  }

  const closedTrades = northStar?.total_trades ?? 0
  const exports = status?.exports_preview ?? []

  return (
    <div className="space-y-6" data-testid="learning-page">
      <PageBrandHeader
        eyebrow="LEARNING"
        title="Learning & shadow evaluation"
        description="Evidence for whether shadow ML should ever influence live trading — measured against the same gain/day bands as Trade Review."
      />
      <p className="text-sm -mt-4 flex flex-wrap gap-x-4 gap-y-1">
        <Link to="/trades/review" className="text-cyan hover:underline">
          Review completed trades →
        </Link>
        <Link to="/roadmap?tab=roadmap" className="text-violet hover:underline">
          Roadmap US-6.6 / US-2.1 →
        </Link>
      </p>

      <LearningNorthStarHero metrics={northStar} />
      <PromotionGateStrip evaluation={evaluation} northStar={northStar} />
      <ArtifactFreshnessBanner status={status} />

      <LearningTabs activeTab={activeTab} onTabChange={setActiveTab}>
        {(tab) => {
          if (tab === 'shadow') return <ShadowPanel />
          if (tab === 'evaluation') return <EvaluationPanel evaluation={evaluation} />
          if (tab === 'rejection') return <RejectionQualityPanel />
          return (
            <AttributionPanel
              closedTrades={closedTrades}
              evaluationCreatedAt={evaluation?.created_at}
            />
          )
        }}
      </LearningTabs>

      <ModelLabPanel runs={runs} />
      <DataLabAccordion exports={exports} />
    </div>
  )
}
