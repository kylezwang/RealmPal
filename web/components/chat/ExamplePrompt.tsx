"use client";
import { useEffect, useRef, useState } from "react";
import type { ExamplePromptConfig, ExamplePromptField } from "@/lib/examplePrompts";

const HOLD_MS = 1250;
/** Delay before this prompt starts deleting. Letter speed stays the same. */
const STAGGER_MS = 500;
const ERASE_MS = 70;

type Variant = "card" | "sidebar" | "row";

function useErasingValue(initial: string, animate: boolean, stagger: number) {
  const [value, setValue] = useState(animate ? initial : "");
  const animating = useRef(animate);
  const remaining = useRef(animate ? initial : "");

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
    }, HOLD_MS + stagger * STAGGER_MS);
    return () => {
      window.clearTimeout(start);
      if (interval) window.clearInterval(interval);
    };
  }, [animate, stagger]);

  function stopAnimation() {
    animating.current = false;
  }

  function write(next: string) {
    remaining.current = next;
    setValue(next);
  }

  return { value, setValue: write, stopAnimation };
}

function PromptInput({
  field,
  name,
  value,
  disabled,
  inputClass,
  onWrite,
  onStop,
}: {
  field: ExamplePromptField;
  name: string;
  value: string;
  disabled?: boolean;
  inputClass: string;
  onWrite: (next: string) => void;
  onStop: () => void;
}) {
  return (
    <input
      type="text"
      value={value}
      onChange={(event) => {
        onStop();
        onWrite(field.sanitize(event.target.value));
      }}
      onPaste={(event) => {
        event.preventDefault();
        onStop();
        onWrite(field.sanitize(event.clipboardData.getData("text")));
      }}
      onFocus={onStop}
      onClick={(event) => event.stopPropagation()}
      maxLength={field.maxLength}
      autoComplete="off"
      autoCorrect="off"
      spellCheck={false}
      inputMode="text"
      name={name}
      aria-label={field.placeholder}
      placeholder={field.placeholder}
      disabled={disabled}
      className={inputClass}
    />
  );
}

export function ExamplePrompt({
  config,
  variant,
  disabled,
  animate: animateProp,
  onSubmit,
}: {
  config: ExamplePromptConfig;
  variant: Variant;
  disabled?: boolean;
  /** Landing cards erase the sample text. In-chat copies stay filled. */
  animate?: boolean;
  onSubmit: (message: string) => void;
}) {
  const animate = animateProp ?? variant === "card";
  const sent = useRef(false);
  const first = useErasingValue(config.initial, animate, config.stagger);
  const second = useErasingValue(config.second?.initial ?? "", animate, config.stagger);

  function submit() {
    const message = config.toMessage(first.value, config.second ? second.value : undefined);
    if (!message || disabled || sent.current) return;
    sent.current = true;
    onSubmit(message);
  }

  const isCard = variant === "card";
  const isRow = variant === "row";
  const paired = Boolean(config.second);
  const pairInline = paired && (isRow || variant === "sidebar");
  const stacked = !pairInline && (config.layout === "stacked" || isRow);

  const fieldClass = isCard || isRow
    ? `${isRow ? "h-7" : "h-9 md:h-8"} rounded-md bg-[#333333] border border-[#454545] px-2 ${isRow ? "text-xs" : "text-base md:text-sm"} text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-[#737373] cursor-text`
    : "h-8 md:h-6 rounded-md bg-[#2a2a2a] border border-[#3a3a3a] px-1.5 text-base md:text-xs text-[#ececec] placeholder-[#525252] focus:outline-none focus:border-[#737373] cursor-text";
  const inputClass = `min-w-0 ${pairInline || stacked ? "w-full" : isCard ? "w-[7.5rem]" : "w-[6.5rem]"} ${fieldClass}`;
  const compactInputClass = `min-w-0 ${pairInline || isRow ? "w-full" : isCard ? "w-[6.75rem]" : "w-[5.5rem]"} ${fieldClass}`;

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
      onClick={() => submit()}
      className={
        isCard || isRow
          ? `min-w-0 rounded-xl bg-[#262626] border border-[#404040] hover:border-white ${isRow ? "px-2 py-2 text-xs" : "px-3 py-2.5 text-sm"} text-[#a3a3a3] cursor-pointer ${
              stacked || pairInline ? "flex flex-col items-stretch gap-1.5" : "flex items-center gap-1.5"
            }`
          : `w-full cursor-pointer text-xs text-[#737373] hover:text-[#ececec] ${
              stacked || pairInline ? "flex flex-col items-stretch gap-1" : "flex items-center gap-1.5"
            }`
      }
    >
      {pairInline ? (
        <div className="flex min-w-0 items-center gap-1.5">
          <span className="whitespace-nowrap">{config.prefix}</span>
          <PromptInput
            field={config}
            name={config.id}
            value={first.value}
            disabled={disabled}
            inputClass={inputClass}
            onWrite={first.setValue}
            onStop={() => {
              first.stopAnimation();
              second.stopAnimation();
            }}
          />
        </div>
      ) : (
        <>
          <span className={stacked ? "leading-snug" : "whitespace-nowrap"}>{config.prefix}</span>
          <PromptInput
            field={config}
            name={config.id}
            value={first.value}
            disabled={disabled}
            inputClass={inputClass}
            onWrite={first.setValue}
            onStop={() => {
              first.stopAnimation();
              second.stopAnimation();
            }}
          />
        </>
      )}
      {config.second && (
        <div className="flex min-w-0 items-center gap-1.5">
          {config.infix && <span className="whitespace-nowrap">{config.infix}</span>}
          <PromptInput
            field={config.second}
            name={`${config.id}-extra`}
            value={second.value}
            disabled={disabled}
            inputClass={compactInputClass}
            onWrite={second.setValue}
            onStop={() => {
              first.stopAnimation();
              second.stopAnimation();
            }}
          />
          {config.suffix && <span className="flex-shrink-0">{config.suffix}</span>}
        </div>
      )}
    </form>
  );
}
