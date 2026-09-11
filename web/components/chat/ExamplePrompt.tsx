"use client";
import { useEffect, useRef, useState } from "react";
import type { ExamplePromptConfig } from "@/lib/examplePrompts";

const HOLD_MS = 1250;
/** Delay before this prompt starts deleting. Letter speed stays the same. */
const STAGGER_MS = 500;
const ERASE_MS = 70;

type Variant = "card" | "sidebar";

export function ExamplePrompt({
  config,
  variant,
  disabled,
  onSubmit,
}: {
  config: ExamplePromptConfig;
  variant: Variant;
  disabled?: boolean;
  onSubmit: (message: string) => void;
}) {
  const animate = variant === "card";
  const [value, setValue] = useState(animate ? config.initial : "");
  const sent = useRef(false);
  const animating = useRef(animate);
  const remaining = useRef(animate ? config.initial : "");

  useEffect(() => {
    if (!animate) return;
    let interval: number | undefined;
    const start = window.setTimeout(() => {
      if (!animating.current) return;
      interval = window.setInterval(() => {
        if (!animating.current) {
          if (interval) window.clearInterval(interval);
          return;
        }
        remaining.current = remaining.current.slice(0, -1);
        setValue(remaining.current);
        if (!remaining.current && interval) {
          window.clearInterval(interval);
          animating.current = false;
        }
      }, ERASE_MS);
    }, HOLD_MS + config.stagger * STAGGER_MS);
    return () => {
      window.clearTimeout(start);
      if (interval) window.clearInterval(interval);
    };
  }, [animate, config.stagger]);

  function stopAnimation() {
    animating.current = false;
  }

  function submit(raw: string) {
    const message = config.toMessage(raw);
    if (!message || disabled || sent.current) return;
    sent.current = true;
    onSubmit(message);
  }

  const isCard = variant === "card";
  const stacked = config.layout === "stacked";

  const inputClass = isCard
    ? `min-w-0 ${stacked ? "w-full" : "w-[7.5rem]"} h-8 rounded-md bg-[#333333] border border-[#454545] px-2 text-sm text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-[#737373] cursor-text`
    : `min-w-0 ${stacked ? "w-full" : "w-[6.5rem]"} h-6 rounded-md bg-[#2a2a2a] border border-[#3a3a3a] px-1.5 text-xs text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-[#737373] cursor-text`;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit(value);
      }}
      onClick={() => submit(value)}
      className={
        isCard
          ? `rounded-xl bg-[#262626] border border-[#404040] hover:border-white px-3 py-2.5 text-sm text-[#a3a3a3] cursor-pointer ${
              stacked ? "flex flex-col items-stretch gap-1.5" : "flex items-center gap-1.5"
            }`
          : `w-full cursor-pointer text-xs text-[#737373] hover:text-[#ececec] ${
              stacked ? "flex flex-col items-stretch gap-1" : "flex items-center gap-1.5"
            }`
      }
    >
      <span className={stacked ? "leading-snug" : "whitespace-nowrap"}>{config.prefix}</span>
      <input
        type="text"
        value={value}
        onChange={(event) => {
          stopAnimation();
          const next = config.sanitize(event.target.value);
          remaining.current = next;
          setValue(next);
        }}
        onPaste={(event) => {
          event.preventDefault();
          stopAnimation();
          const next = config.sanitize(event.clipboardData.getData("text"));
          remaining.current = next;
          setValue(next);
        }}
        onFocus={stopAnimation}
        onClick={(event) => event.stopPropagation()}
        onBlur={() => submit(value)}
        maxLength={config.maxLength}
        autoComplete="off"
        autoCorrect="off"
        spellCheck={false}
        inputMode="text"
        name={config.id}
        aria-label={config.placeholder}
        placeholder={config.placeholder}
        disabled={disabled}
        className={inputClass}
      />
    </form>
  );
}
