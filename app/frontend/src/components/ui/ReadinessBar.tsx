interface ReadinessBarProps {
  ready: number;
  needs: number;
  building: number;
  invalid: number;
  duplicate: number;
}

export function ReadinessBar({
  ready,
  needs,
  building,
  invalid,
  duplicate,
}: ReadinessBarProps) {
  const segments = [
    { label: "可采", value: ready, className: "bg-success" },
    { label: "待接入", value: needs + building, className: "bg-warning" },
    { label: "无效", value: invalid, className: "bg-danger" },
    { label: "重复", value: duplicate, className: "bg-line-strong" },
  ];
  const total = segments.reduce((sum, segment) => sum + segment.value, 0);
  const summary = segments
    .filter((segment) => segment.value > 0)
    .map((segment) => `${segment.label} ${segment.value}`)
    .join(" · ");

  return (
    <div
      className="flex h-1.5 w-full overflow-hidden rounded-full bg-surface-sunken"
      role="img"
      aria-label={total ? `站点状态：${summary}` : "暂无站点"}
      title={total ? summary : "暂无站点"}
    >
      {total > 0
        ? segments.map((segment) =>
            segment.value > 0 ? (
              <span
                key={segment.label}
                className={segment.className}
                style={{ flexGrow: segment.value, minWidth: 4 }}
              />
            ) : null,
          )
        : null}
    </div>
  );
}
