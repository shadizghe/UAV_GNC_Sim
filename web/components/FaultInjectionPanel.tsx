"use client";

import { Plus, Trash2, Wrench, ZapOff, Satellite } from "lucide-react";
import { useAppStore } from "@/lib/store";
import type { FaultConfig, MotorFault, WindowFault } from "@/lib/types";
import { cn } from "@/lib/utils";

/**
 * Fault Injection panel — toggleable motor failures, IMU dropouts, and
 * GPS-denied windows.  Lives alongside the rest of the workspace tabs.
 *
 * Each fault is a small card with start/end (and severity for motors).
 * "Add" appends a new template fault; "Trash" removes it.  Saving
 * doesn't fire a sim run automatically — the user clicks Run to see
 * how the controller responds.
 */

const ROTORS = [
  { id: 0, label: "FR", color: "#ff5252" },
  { id: 1, label: "BR", color: "#ff8c42" },
  { id: 2, label: "BL", color: "#ffc107" },
  { id: 3, label: "FL", color: "#7fdfff" },
] as const;

export function FaultInjectionPanel() {
  const { faultConfig, setFaultConfig, clearFaults } = useAppStore();

  const update = (next: FaultConfig) => setFaultConfig(next);

  const addMotor = () => update({
    ...faultConfig,
    motor: [...faultConfig.motor,
      { rotor: 0, t_start: 5, t_end: 8, severity: 0 }],
  });
  const addImu = () => update({
    ...faultConfig,
    imu: [...faultConfig.imu, { t_start: 4, t_end: 5 }],
  });
  const addGps = () => update({
    ...faultConfig,
    gps: [...faultConfig.gps, { t_start: 6, t_end: 8 }],
  });

  const totalFaults =
    faultConfig.motor.length + faultConfig.imu.length + faultConfig.gps.length;

  return (
    <section className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <header className="flex items-center gap-2">
          <span className="h-5 w-1 rounded-sm bg-red" />
          <div>
            <h2 className="text-[0.74rem] font-semibold uppercase tracking-[0.18em] text-red">
              Fault Injection
            </h2>
            <p className="mt-0.5 text-xs text-muted">
              Inject motor failures, IMU dropouts, and GPS-denied windows
            </p>
          </div>
        </header>
        {totalFaults > 0 && (
          <button
            type="button"
            onClick={clearFaults}
            className="flex h-8 items-center gap-1.5 rounded-md border border-red/30 bg-red/10 px-2.5 text-[0.7rem] font-semibold uppercase tracking-wider text-red transition-colors hover:bg-red/15"
          >
            <Trash2 className="h-3 w-3" />
            Clear all
          </button>
        )}
      </div>

      {/* Motor failures */}
      <FaultGroup
        icon={<Wrench className="h-3.5 w-3.5" />}
        label="Motor failures"
        accent="amber"
        onAdd={addMotor}
        empty={faultConfig.motor.length === 0}
        emptyHint="Disable a rotor for a window — watch the controller scramble to compensate."
      >
        {faultConfig.motor.map((fault, idx) => (
          <MotorFaultRow
            key={idx}
            fault={fault}
            onChange={(patch) => update({
              ...faultConfig,
              motor: faultConfig.motor.map((f, i) => i === idx ? { ...f, ...patch } : f),
            })}
            onDelete={() => update({
              ...faultConfig,
              motor: faultConfig.motor.filter((_, i) => i !== idx),
            })}
          />
        ))}
      </FaultGroup>

      {/* IMU dropouts */}
      <FaultGroup
        icon={<ZapOff className="h-3.5 w-3.5" />}
        label="IMU dropouts"
        accent="violet"
        onAdd={addImu}
        empty={faultConfig.imu.length === 0}
        emptyHint="Freezes attitude/rate measurements — controller flies blind on attitude."
      >
        {faultConfig.imu.map((fault, idx) => (
          <WindowRow
            key={idx}
            fault={fault}
            onChange={(patch) => update({
              ...faultConfig,
              imu: faultConfig.imu.map((f, i) => i === idx ? { ...f, ...patch } : f),
            })}
            onDelete={() => update({
              ...faultConfig,
              imu: faultConfig.imu.filter((_, i) => i !== idx),
            })}
          />
        ))}
      </FaultGroup>

      {/* GPS denied */}
      <FaultGroup
        icon={<Satellite className="h-3.5 w-3.5" />}
        label="GPS denied"
        accent="cyan"
        onAdd={addGps}
        empty={faultConfig.gps.length === 0}
        emptyHint="Skips position updates — EKF dead-reckons until reacquisition."
      >
        {faultConfig.gps.map((fault, idx) => (
          <WindowRow
            key={idx}
            fault={fault}
            onChange={(patch) => update({
              ...faultConfig,
              gps: faultConfig.gps.map((f, i) => i === idx ? { ...f, ...patch } : f),
            })}
            onDelete={() => update({
              ...faultConfig,
              gps: faultConfig.gps.filter((_, i) => i !== idx),
            })}
          />
        ))}
      </FaultGroup>
    </section>
  );
}

type AccentClass = "amber" | "violet" | "cyan";

const accentClasses: Record<AccentClass, { stripe: string; pill: string; text: string; border: string }> = {
  amber:  { stripe: "bg-amber",  pill: "bg-amber/12",  text: "text-amber",  border: "border-amber/25" },
  violet: { stripe: "bg-violet", pill: "bg-violet/12", text: "text-violet", border: "border-violet/25" },
  cyan:   { stripe: "bg-cyan",   pill: "bg-cyan/12",   text: "text-cyan",   border: "border-cyan/25" },
};

function FaultGroup({
  icon, label, accent, onAdd, empty, emptyHint, children,
}: {
  icon: React.ReactNode;
  label: string;
  accent: AccentClass;
  onAdd: () => void;
  empty: boolean;
  emptyHint: string;
  children: React.ReactNode;
}) {
  const c = accentClasses[accent];
  return (
    <section className={cn("panel space-y-2 p-3", c.border)}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className={cn("grid h-6 w-6 place-items-center rounded-md", c.pill, c.text)}>
            {icon}
          </span>
          <span className={cn("text-[0.7rem] font-semibold uppercase tracking-[0.16em]", c.text)}>
            {label}
          </span>
        </div>
        <button
          type="button"
          onClick={onAdd}
          className={cn(
            "flex h-7 items-center gap-1 rounded-md border px-2 text-[0.66rem] font-semibold uppercase tracking-wider transition-colors",
            c.border, c.pill, c.text,
            "hover:brightness-125",
          )}
        >
          <Plus className="h-3 w-3" />
          Add
        </button>
      </div>

      {empty ? (
        <p className="text-[0.7rem] leading-snug text-muted">{emptyHint}</p>
      ) : (
        <div className="space-y-1.5">{children}</div>
      )}
    </section>
  );
}

function MotorFaultRow({
  fault, onChange, onDelete,
}: {
  fault: MotorFault;
  onChange: (patch: Partial<MotorFault>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="grid grid-cols-[3rem_3.5rem_3.5rem_4.5rem_2rem] items-center gap-1.5 rounded-md bg-bg/45 p-1.5">
      <select
        value={fault.rotor}
        onChange={(e) => onChange({ rotor: Number(e.target.value) as 0 | 1 | 2 | 3 })}
        className="field h-7 px-1 text-[0.7rem] font-semibold"
        style={{ color: ROTORS[fault.rotor].color }}
      >
        {ROTORS.map((r) => (
          <option key={r.id} value={r.id}>{r.label}</option>
        ))}
      </select>
      <NumberCell label="t₀" value={fault.t_start} step={0.1} min={0}
        onChange={(v) => onChange({ t_start: v })} />
      <NumberCell label="t₁" value={fault.t_end} step={0.1} min={0.1}
        onChange={(v) => onChange({ t_end: v })} />
      <NumberCell label="sev" value={fault.severity} step={0.1} min={0} max={1}
        onChange={(v) => onChange({ severity: Math.max(0, Math.min(1, v)) })} />
      <DeleteCell onClick={onDelete} />
    </div>
  );
}

function WindowRow({
  fault, onChange, onDelete,
}: {
  fault: WindowFault;
  onChange: (patch: Partial<WindowFault>) => void;
  onDelete: () => void;
}) {
  return (
    <div className="grid grid-cols-[1fr_1fr_2rem] items-center gap-1.5 rounded-md bg-bg/45 p-1.5">
      <NumberCell label="start [s]" value={fault.t_start} step={0.1} min={0}
        onChange={(v) => onChange({ t_start: v })} />
      <NumberCell label="end [s]" value={fault.t_end} step={0.1} min={0.1}
        onChange={(v) => onChange({ t_end: v })} />
      <DeleteCell onClick={onDelete} />
    </div>
  );
}

function NumberCell({
  label, value, onChange, step, min, max,
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  step?: number;
  min?: number;
  max?: number;
}) {
  return (
    <label className="flex flex-col gap-0.5">
      <span className="text-[0.6rem] uppercase tracking-wider text-muted">{label}</span>
      <input
        type="number"
        value={Number.isFinite(value) ? value : 0}
        step={step}
        min={min}
        max={max}
        onChange={(e) => onChange(Number(e.target.value))}
        className="field h-7 px-1.5 font-mono text-[0.72rem]"
      />
    </label>
  );
}

function DeleteCell({ onClick }: { onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="grid h-7 w-7 place-items-center self-end rounded-md border border-red/25 bg-red/10 text-red transition-colors hover:bg-red/15"
    >
      <Trash2 className="h-3 w-3" />
    </button>
  );
}
