"use client";

import { useEffect, useRef } from "react";

interface PlotlyChartProps {
  data: unknown[];
  layout: Record<string, unknown>;
  config?: Record<string, unknown>;
  className?: string;
}

export function PlotlyChart({ data, layout, config, className }: PlotlyChartProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    let active = true;

    void import("plotly.js-dist-min").then((mod) => {
      if (!active) return;
      const Plotly = mod.default;
      void Plotly.react(node, data, layout, {
        displayModeBar: false,
        responsive: true,
        ...config,
      });
    });

    return () => {
      active = false;
      void import("plotly.js-dist-min").then((mod) => {
        if (node) mod.default.purge(node);
      });
    };
  }, [config, data, layout]);

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const observer = new ResizeObserver(() => {
      void import("plotly.js-dist-min").then((mod) => mod.default.Plots?.resize(node));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  return <div ref={ref} className={className ?? "h-[360px] w-full"} />;
}
