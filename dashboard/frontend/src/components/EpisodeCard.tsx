import React from "react";
import type { StrategyChangeEpisode } from "../types";

interface EpisodeCardProps {
  episode: StrategyChangeEpisode;
  onClick?: () => void;
}

const changeTypeBadgeColor: Record<string, string> = {
  strategy: "bg-violet-900/40 text-violet-300 border-violet-700",
  risk: "bg-red-900/40 text-red-300 border-red-700",
  execution: "bg-amber-900/40 text-amber-300 border-amber-700",
  screening: "bg-blue-900/40 text-blue-300 border-blue-700",
  opportunity: "bg-emerald-900/40 text-emerald-300 border-emerald-700",
  system: "bg-slate-800/40 text-slate-300 border-slate-700",
};

const changeTypeLabel: Record<string, string> = {
  strategy: "Strategy",
  risk: "Risk",
  execution: "Execution",
  screening: "Screening",
  opportunity: "Opportunity",
  system: "System",
};

/**
 * EpisodeCard displays a single strategy change episode.
 * Shows: title, change_type badge, date range, commit count, and affected files summary.
 */
export const EpisodeCard: React.FC<EpisodeCardProps> = ({ episode, onClick }) => {
  const episodeExtras = episode as StrategyChangeEpisode & {
    commit_count?: number;
    affected_files?: string[];
  };

  const formatDate = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
  };

  const startDate = formatDate(episode.effective_start_at);
  const endDate = episode.effective_end_at ? formatDate(episode.effective_end_at) : "ongoing";
  const dateRange = `${startDate} – ${endDate}`;

  const badgeClass = changeTypeBadgeColor[episode.change_type] || changeTypeBadgeColor.system;
  const typeLabel = changeTypeLabel[episode.change_type] || "System";

  return (
    <div
      onClick={onClick}
      className={`
        p-3 rounded-lg border border-slate-700/50 bg-slate-900/40
        hover:bg-slate-800/60 hover:border-slate-600 transition-all
        ${onClick ? "cursor-pointer" : ""}
      `}
    >
      {/* Header: Title + Badge */}
      <div className="flex items-start justify-between gap-3 mb-2">
        <h4 className="text-sm font-medium text-slate-100 flex-1">{episode.title}</h4>
        <div
          className={`
            px-2.5 py-0.5 text-xs font-semibold rounded-full border
            whitespace-nowrap flex-shrink-0 ${badgeClass}
          `}
        >
          {typeLabel}
        </div>
      </div>

      {/* Subtitle: Date range + Commit count */}
      <div className="flex items-center justify-between text-xs text-slate-400 mb-2">
        <span>{dateRange}</span>
        {episodeExtras.commit_count && (
          <span className="text-slate-500">
            {episodeExtras.commit_count} commit{episodeExtras.commit_count !== 1 ? "s" : ""}
          </span>
        )}
      </div>

      {/* Summary text (if provided) */}
      {episode.summary && (
        <p className="text-xs text-slate-300 mb-2 line-clamp-2">{episode.summary}</p>
      )}

      {/* Affected files (if provided) */}
      {episodeExtras.affected_files && episodeExtras.affected_files.length > 0 && (
        <div className="text-xs text-slate-500">
          <span className="font-semibold">Files:</span>{" "}
          {episodeExtras.affected_files.slice(0, 3).join(", ")}
          {episodeExtras.affected_files.length > 3 && ` +${episodeExtras.affected_files.length - 3}`}
        </div>
      )}
    </div>
  );
};
