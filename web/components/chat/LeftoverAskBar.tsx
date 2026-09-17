"use client";
import { examplePromptShellClass, LANDING_EXAMPLE_PROMPTS } from "@/lib/examplePrompts";
import { leftoverAskLead } from "@/lib/usageCopy";
import { ChevronToggle } from "./ChevronToggle";
import { ExamplePrompt } from "./ExamplePrompt";

interface Props {
  signedIn: boolean;
  expanded: boolean;
  onToggle: () => void;
  disabled?: boolean;
  onSubmit: (message: string) => void;
}

export function LeftoverAskBar({
  signedIn,
  expanded,
  onToggle,
  disabled,
  onSubmit,
}: Props) {
  return (
    <div className={`relative ${expanded ? "mb-3" : "mb-2 h-5"}`}>
      <div className="absolute top-0 right-0">
        <ChevronToggle
          expanded={expanded}
          onToggle={onToggle}
          hideLabel="Hide leftover suggestions"
          showLabel="Show leftover suggestions"
        />
      </div>
      {expanded && (
        <div className="pr-8">
          <p className="text-sm leading-relaxed text-[#a3a3a3] mb-3">
            {leftoverAskLead(signedIn)}
          </p>
          <div className="grid grid-cols-3 md:grid-cols-4 gap-2 w-full">
            {LANDING_EXAMPLE_PROMPTS.map((config) => (
              <div key={config.id} className={examplePromptShellClass(config.id)}>
                <ExamplePrompt
                  config={config}
                  variant="row"
                  animate={false}
                  disabled={disabled}
                  onSubmit={onSubmit}
                />
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
