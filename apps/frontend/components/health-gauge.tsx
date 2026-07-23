"use client";

import React from "react";
import { HealthScore } from "@/lib/types";
import { getGradeColor } from "@/lib/utils";

interface HealthGaugeProps {
  healthScore: HealthScore;
}

export function HealthGauge({ healthScore }: HealthGaugeProps) {
  const { score, grade, critical_issues, warning_issues, info_issues } = healthScore;
  const gradeStyle = getGradeColor(grade);

  // SVG Circular progress calculation
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  const strokeDashoffset = circumference - (score / 100) * circumference;

  return (
    <div className="flex items-center gap-6 rounded-2xl border border-border/70 bg-card p-5 shadow-apple transition-all hover:shadow-apple-hover">
      <div className="relative flex items-center justify-center">
        <svg className="h-28 w-28 -rotate-90 transform">
          <circle
            cx="56"
            cy="56"
            r={radius}
            className="stroke-muted"
            strokeWidth="8"
            fill="transparent"
          />
          <circle
            cx="56"
            cy="56"
            r={radius}
            stroke={gradeStyle.stroke}
            strokeWidth="8"
            strokeDasharray={circumference}
            strokeDashoffset={strokeDashoffset}
            strokeLinecap="round"
            fill="transparent"
            className="transition-all duration-1000 ease-out"
          />
        </svg>
        <div className="absolute flex flex-col items-center justify-center text-center">
          <span className="text-2xl font-bold tracking-tight text-foreground">
            {score}
          </span>
          <span className="text-[10px] font-semibold tracking-wider text-muted-foreground uppercase">
            / 100
          </span>
        </div>
      </div>

      <div className="flex flex-col space-y-1.5">
        <div className="flex items-center gap-2">
          <span
            className={`inline-flex items-center justify-center rounded-xl px-3 py-1 text-sm font-bold shadow-sm ${gradeStyle.bg} ${gradeStyle.text}`}
          >
            Grade {grade}
          </span>
          <span className="text-xs font-medium text-muted-foreground">
            Health Score
          </span>
        </div>
        <div className="flex items-center gap-3 pt-1 text-xs text-muted-foreground">
          <span className="flex items-center gap-1 font-medium text-rose-600 dark:text-rose-400">
            <span className="h-2 w-2 rounded-full bg-rose-500" />
            {critical_issues} Critical
          </span>
          <span className="flex items-center gap-1 font-medium text-amber-600 dark:text-amber-400">
            <span className="h-2 w-2 rounded-full bg-amber-500" />
            {warning_issues} Warnings
          </span>
          <span className="flex items-center gap-1 font-medium text-blue-600 dark:text-blue-400">
            <span className="h-2 w-2 rounded-full bg-blue-500" />
            {info_issues} Info
          </span>
        </div>
      </div>
    </div>
  );
}
