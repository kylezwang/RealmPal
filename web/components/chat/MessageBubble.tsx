"use client";
import { useEffect, useState } from "react";
import Image from "next/image";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import { SWORD_SPRITE, FAME_SPRITE } from "@/lib/sprites";
import { fetchPlayer, type PlayerProfile, type ItemProfile, type DungeonGuide, type FeedbackRating } from "@/lib/api";
import { PlayerCard } from "./PlayerCard";
import { ItemCardGrid, ItemChip } from "./ItemCard";
import { LoadoutRow } from "./LoadoutRow";
import { SkinPortrait } from "./SkinPortrait";
import { DungeonDrops, DungeonHeader, DungeonLayouts } from "./DungeonHeader";
import { GuestAvatar } from "./GuestAvatar";
import { PetSprite } from "./PetCompanion";
import { MessageActions } from "./MessageActions";
import { cleanItemName, findItem, itemTokensToLinks, stripItemTokens } from "@/lib/itemLookup";
import { resolveLoadoutShowcase, stripLoadoutToken } from "@/lib/loadoutShowcase";
import { parseSkinToken, parseSkinFromPrompt, stripSkinToken } from "@/lib/skinShowcase";

const THINKING_LINES = ["Thinking...", "Working on it...", "Looking that up..."];
const AVATAR_SIZE = 52;
const AVATAR_SPRITE = 29;

interface Props {
  role: "user" | "assistant";
  content: string;
  isStreaming?: boolean;
  /** Attached when this response was about a specific player | renders a
   * rich character/equipment card (sprites + hover tooltips) below the text. */
  playerProfile?: PlayerProfile;
  /** Only render PlayerCard's full per-class exaltations breakdown when
   * the user actually asked about exaltations. */
  showExaltationTable?: boolean;
  /** Dedicated wiki infobox cards for items named in this reply. */
  items?: ItemProfile[];
  /** Names we have started fetching, used for glimmer placeholders. */
  pendingItemNames?: string[];
  /** Portal, graves, layouts, and drops scraped from the RealmEye dungeon page. */
  dungeonGuide?: DungeonGuide;
  /** Sidebar pet, same crop as PetCompanion. */
  userPet?: PlayerProfile["top_pet"];
  /** Stable id for copy/feedback tracking on finished assistant replies. */
  messageId?: string;
  /** User prompt that produced this assistant reply. */
  prompt?: string;
  feedback?: FeedbackRating;
  onFeedback?: (rating: FeedbackRating) => void;
}

function childText(children: React.ReactNode): string {
  if (children == null || typeof children === "boolean") return "";
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(childText).join("");
  if (typeof children === "object" && "props" in children) {
    return childText((children as { props?: { children?: React.ReactNode } }).props?.children);
  }
  return "";
}

const SECTION_TITLE = /^(recommended loadout|top(?:\s+\d+)?\s+ring options|top(?:\s+\d+)?\s+realmshark loadouts|sources):?\s*$/i;

const PLAYER_SUMMARY_LINE =
  /^\s*(?:[-*]\s*)?\*{0,2}(Fame|Account fame|Guild|Total exaltations|Top pet|Last seen|Characters)\b/i;
const CLASS_GEAR_LINE =
  /\b(Rogue|Archer|Wizard|Priest|Warrior|Knight|Paladin|Assassin|Necromancer|Huntress|Mystic|Trickster|Sorcerer|Ninja|Samurai|Bard|Summoner|Kensei|Druid)\b[\s\S]{0,80}\b(fame|\d+\s*\/\s*8)\b/i;
const GEAR_TABLE_HEADER =
  /\bclass\b.+\b(fame|weapon|ability|armor|ring)\b/i;

function ThinkingLabel() {
  const [index, setIndex] = useState(0);
  useEffect(() => {
    const id = window.setInterval(
      () => setIndex((current) => (current + 1) % THINKING_LINES.length),
      2200,
    );
    return () => window.clearInterval(id);
  }, []);
  return (
    <p className="thinking-subtitle text-sm text-[#8a8a8a] italic" aria-live="polite">
      {THINKING_LINES[index]}
    </p>
  );
}

function PlayerSummary({ profile }: { profile: PlayerProfile }) {
  const [live, setLive] = useState(profile);

  useEffect(() => {
    setLive(profile);
  }, [profile]);

  useEffect(() => {
    if (live.account_fame != null) return;
    let cancelled = false;
    fetchPlayer(live.username)
      .then((fresh) => {
        if (!cancelled && fresh.account_fame != null) setLive(fresh);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [live.account_fame, live.username]);

  const guild = live.guild
    ? `${live.guild}${live.guild_rank ? ` (${live.guild_rank})` : ""}`
    : "No guild";
  const items: { label: string; value: string }[] = [
    live.fame != null ? { label: "Fame", value: live.fame.toLocaleString() } : null,
    live.account_fame != null
      ? { label: "Account fame", value: live.account_fame.toLocaleString() }
      : null,
    { label: "Guild", value: guild },
    profile.total_exaltations != null
      ? { label: "Total exaltations", value: profile.total_exaltations.toLocaleString() }
      : null,
    profile.top_pet?.name ? { label: "Top pet", value: profile.top_pet.name } : null,
    { label: "Last seen", value: profile.last_seen || "Unknown" },
  ].filter((item): item is { label: string; value: string } => Boolean(item));

  if (items.length === 0) return null;

  return (
    <ul className="list-disc pl-5 mb-2 space-y-0.5">
      {items.map(({ label, value }) => (
        <li key={label} className="pl-0.5">
          {label}:{" "}
          {label === "Fame" || label === "Account fame" ? (
            <span className="inline-flex items-center gap-1.5 align-middle">
              <img
                src={FAME_SPRITE}
                alt=""
                width={16}
                height={16}
                style={{ imageRendering: "pixelated", width: 16, height: 16 }}
              />
              <strong className="font-semibold text-white">{value}</strong>
            </span>
          ) : label === "Top pet" && live.top_pet ? (
            <span className="inline-flex items-center gap-1.5 align-middle">
              <PetSprite pet={live.top_pet} size={28} />
              <strong className="font-semibold text-white">{value}</strong>
            </span>
          ) : (
            <strong className="font-semibold text-white">{value}</strong>
          )}
        </li>
      ))}
    </ul>
  );
}

/** Drop Fame/Guild bullets and any character-gear dump the UI already shows. */
function stripRestatedPlayerSummary(content: string): string {
  if (!content.trim()) return content;
  const sources = content.match(/^(#{1,4}\s*Sources\b)/im);
  const splitAt = sources?.index ?? -1;
  const head = splitAt >= 0 ? content.slice(0, splitAt) : content;
  const tail = splitAt >= 0 ? content.slice(splitAt) : "";

  const kept: string[] = [];
  let inTable = false;
  for (const line of head.split("\n")) {
    const trimmed = line.trim();
    const tableRow = /^\|/.test(trimmed);
    if (tableRow) {
      inTable = true;
      continue;
    }
    if (inTable) {
      inTable = false;
    }
    if (!trimmed) {
      kept.push(line);
      continue;
    }
    if (PLAYER_SUMMARY_LINE.test(line)) continue;
    if (GEAR_TABLE_HEADER.test(trimmed)) continue;
    if (CLASS_GEAR_LINE.test(trimmed)) continue;
    if (/characters and their gear|look at .+['’]?s characters|their gear:?\s*$/i.test(trimmed)) {
      continue;
    }
    kept.push(line);
  }

  const rest = kept.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  return [rest, tail].filter(Boolean).join("\n\n") || tail;
}

function sectionHeading(children: React.ReactNode) {
  return (
    <h3 className="text-lg font-semibold text-[#ececec] leading-tight mt-3 mb-1.5 first:mt-0">
      {children}
    </h3>
  );
}

function markdownComponents(
  items: ItemProfile[] | undefined,
  pendingItemNames: string[] | undefined,
  dungeonGuide?: DungeonGuide,
): Components {
  return {
    p: ({ children }) => {
      const text = childText(children).trim();
      if (SECTION_TITLE.test(text)) {
        return sectionHeading(children);
      }
      return <p className="mb-2 last:mb-0">{children}</p>;
    },
    h1: ({ children }) => (
      <p className="text-xl font-semibold text-[#ececec] leading-tight mb-2 first:mt-0">
        {children}
      </p>
    ),
    h2: ({ children }) => sectionHeading(children),
    h3: ({ children }) => sectionHeading(children),
    h4: ({ children }) => sectionHeading(children),
    ul: ({ children }) => <ul className="list-disc pl-5 mb-2 space-y-0.5">{children}</ul>,
    ol: ({ children }) => <ol className="list-decimal pl-5 mb-2 space-y-0.5">{children}</ol>,
    li: ({ children }) => <li className="pl-0.5">{children}</li>,
    strong: ({ children }) => <strong className="font-semibold text-white">{children}</strong>,
    em: ({ children }) => <em className="italic">{children}</em>,
    a: ({ children, href }) => {
      const label = childText(children);
      const name = href?.startsWith("item://")
        ? decodeURIComponent(href.slice("item://".length))
        : label;
      const item = findItem(items, name, href);
      if (item || href?.startsWith("item://")) {
        const key = cleanItemName(name).toLowerCase();
        const loading = !item && (pendingItemNames ?? []).some(
          (pending) => cleanItemName(pending).toLowerCase() === key
        );
        return <ItemChip name={name || item?.name || ""} item={item} loading={loading} />;
      }
      return (
        <a href={href} target="_blank" rel="noopener noreferrer" className="text-blue-400 hover:underline">
          {children}
        </a>
      );
    },
    code: ({ children, className }) => {
      if (className) {
        return (
          <pre className="bg-[#303030] rounded-lg p-2.5 my-2 overflow-x-auto text-xs">
            <code className="font-mono">{children}</code>
          </pre>
        );
      }
      return <code className="bg-[#303030] rounded px-1 py-0.5 text-sm font-mono">{children}</code>;
    },
    blockquote: ({ children }) => (
      <blockquote className="border-l-2 border-[#4a4a4a] pl-3 italic text-[#c0c0c0] my-2">{children}</blockquote>
    ),
    hr: () => <hr className="border-[#3a3a3a] my-3" />,
    table: ({ children }) => (
      <div className="table-scroll my-2">
        <table className="text-xs border-collapse w-max max-w-none">{children}</table>
      </div>
    ),
    thead: ({ children }) => <thead className="border-b border-[#4a4a4a]">{children}</thead>,
    th: ({ children }) => (
      <th className="text-left font-semibold px-2.5 py-1.5 whitespace-nowrap">{children}</th>
    ),
    td: ({ children }) => (
      <td className="px-2.5 py-1.5 border-t border-[#333333] whitespace-nowrap align-middle">{children}</td>
    ),
    img: ({ src, alt }) => {
      if (!src) return null;
      const isLayout = dungeonGuide?.layouts.some((layout) => layout.url === src);
      return (
        <img
          src={src}
          alt={alt || ""}
          className={
            isLayout
              ? "my-2 max-w-md max-h-72 w-auto h-auto mx-auto"
              : "my-2 max-w-full max-h-96 h-auto w-auto"
          }
          style={{ imageRendering: "pixelated" }}
        />
      );
    },
  };
}

function stripMatchingDungeonTitle(content: string, guide?: DungeonGuide): string {
  if (!guide || !content.trim()) return content;
  const title = guide.title.replace(/\s*[-–—]\s*the RotMG Wiki.*$/i, "").trim();
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return content
    .replace(new RegExp(`^#{1,3}\\s*${escaped}\\s*(?:guide)?\\s*$`, "im"), "")
    .replace(new RegExp(`^#{1,3}\\s*${escaped}\\s*[-–—]\\s*the RotMG Wiki.*$`, "im"), "")
    .replace(new RegExp(`^${escaped}\\s*[-–—]\\s*the RotMG Wiki.*$`, "im"), "")
    .trimStart();
}

function stripDungeonDropsSection(content: string): string {
  return content
    .replace(/^#{1,3}\s+Drops of Interest[^\n]*\n(?:(?!#{1,3}\s).*\n?)*/gim, "")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function stripDungeonGuideMarkdown(content: string, guide: DungeonGuide): string {
  let text = stripMatchingDungeonTitle(content, guide);
  text = stripDungeonDropsSection(text);

  for (const layout of guide.layouts) {
    const url = layout.url.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    text = text.replace(new RegExp(`!\\[[^\\]]*\\]\\(${url}\\)`, "gi"), "");
  }

  text = text.replace(/^#{1,4}\s+Example Layout[^\n]*\n(?:(?!#{1,4}\s).*\n?)*/gim, "");
  text = text.replace(/^#{1,4}\s+Layout[^\n]*\n(?:(?!#{1,4}\s).*\n?)*/gim, "");
  text = text.replace(/^Last updated:.*$/gim, "");
  text = text.replace(/^Back to top\s*$/gim, "");
  text = text.replace(/^Contents\s*$/gim, "");
  text = text.replace(/^Difficulty:\s*\d+(?:\.\d+)?\s*\/\s*10.*$/gim, "");

  const title = guide.title.replace(/\s*[-–—]\s*the RotMG Wiki.*$/i, "").trim();
  const escaped = title.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  text = text.replace(
    new RegExp(`^#{1,3}\\s*${escaped}\\s*[-–—]\\s*the RotMG Wiki.*$`, "gim"),
    "",
  );

  return text.replace(/\n{3,}/g, "\n\n").trim();
}

function splitSources(content: string): { body: string; sources: string } {
  const match = content.match(/^#{1,3}\s+Sources\b/im);
  if (!match || match.index == null) return { body: content, sources: "" };
  return {
    body: content.slice(0, match.index).trimEnd(),
    sources: content.slice(match.index).trimStart(),
  };
}

function parseContent(
  content: string,
  items: ItemProfile[] | undefined,
  pendingItemNames: string[] | undefined,
  dungeonGuide?: DungeonGuide,
): React.ReactNode {
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={markdownComponents(items, pendingItemNames, dungeonGuide)}
    >
      {itemTokensToLinks(stripLoadoutToken(content))}
    </ReactMarkdown>
  );
}

export function MessageBubble({
  role,
  content,
  isStreaming,
  playerProfile,
  showExaltationTable,
  items,
  pendingItemNames,
  dungeonGuide,
  userPet,
  messageId,
  prompt,
  feedback,
  onFeedback,
}: Props) {
  const isUser = role === "user";
  const showThinking = Boolean(isStreaming && !content.trim());
  const displayContent = !isUser && playerProfile
    ? stripRestatedPlayerSummary(content)
    : !isUser && dungeonGuide
      ? stripDungeonGuideMarkdown(content, dungeonGuide)
      : !isUser
        ? stripMatchingDungeonTitle(content, dungeonGuide)
        : content;
  const { body: guideBody, sources: guideSources } =
    !isUser && dungeonGuide && !isStreaming
      ? splitSources(displayContent)
      : { body: displayContent, sources: "" };
  const showcaseItemCount = pendingItemNames?.length || items?.length || 0;
  const loadout = !isUser
    ? resolveLoadoutShowcase(prompt, content, showcaseItemCount)
    : null;
  const skinSpec = !isUser && !loadout
    ? parseSkinToken(content) ?? parseSkinFromPrompt(prompt)
    : null;
  const showSkin = Boolean(skinSpec);
  const markdownSource = skinSpec
    ? stripSkinToken(stripLoadoutToken(guideBody || displayContent))
    : loadout
      ? stripItemTokens(stripLoadoutToken(guideBody || displayContent))
      : guideBody || displayContent;

  return (
    <div className={`flex gap-3 px-4 py-5 animate-fade-in min-w-0 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      <div
        className={`flex-shrink-0 mt-3 ${
          isUser
            ? ""
            : "rounded-full overflow-hidden flex items-center justify-center bg-[#262626] border border-[#404040]"
        }`}
        style={isUser ? undefined : { width: AVATAR_SIZE, height: AVATAR_SIZE }}
        aria-hidden="true"
      >
        {isUser ? (
          <GuestAvatar pet={userPet} size={AVATAR_SIZE} />
        ) : (
          <Image
            src={SWORD_SPRITE}
            alt=""
            width={AVATAR_SPRITE}
            height={AVATAR_SPRITE}
            style={{ imageRendering: "pixelated" }}
            unoptimized
          />
        )}
      </div>

      <div
        className={`min-w-0 rounded-2xl px-4 py-3 text-sm leading-relaxed prose-realm
          ${isUser
            ? "max-w-[80%] bg-[#2a2a2a] text-[#ececec] rounded-tr-sm"
            : "max-w-full flex-1 bg-transparent text-[#ececec] rounded-tl-sm"
          }`}
        role="article"
        aria-label={`${role} message`}
      >
        {!isUser && playerProfile && (
          <p className="text-xl font-semibold text-[#ececec] leading-tight mb-2">{playerProfile.username}</p>
        )}
        {!isUser && playerProfile && <PlayerSummary profile={playerProfile} />}
        {!isUser && dungeonGuide && <DungeonHeader guide={dungeonGuide} />}
        {showThinking ? (
          <ThinkingLabel />
        ) : markdownSource.trim() ? (
          parseContent(
            loadout ? stripItemTokens(markdownSource) : markdownSource,
            items,
            pendingItemNames,
            dungeonGuide,
          )
        ) : null}
        {!isUser && dungeonGuide && <DungeonLayouts guide={dungeonGuide} />}
        {!isUser && dungeonGuide && !isStreaming && <DungeonDrops guide={dungeonGuide} />}
        {!isUser && dungeonGuide && !isStreaming && guideSources && (
          parseContent(guideSources, items, pendingItemNames, dungeonGuide)
        )}
        {isStreaming && !showThinking && (
          <span className="inline-block w-2 h-4 bg-white ml-1 animate-cursor-blink" aria-label="typing" />
        )}
        {!isUser && playerProfile && (
          <PlayerCard profile={playerProfile} showExaltationTable={showExaltationTable} />
        )}
        {!isUser && showSkin && <SkinPortrait spec={skinSpec} />}
        {!isUser && loadout && (
          <LoadoutRow items={items} pendingNames={pendingItemNames} showcase={loadout} />
        )}
        {!isUser && !loadout && !showSkin && (
          <ItemCardGrid items={items} pendingNames={pendingItemNames} />
        )}
        {!isUser && !isStreaming && Boolean(content.trim()) && messageId && onFeedback && (
          <MessageActions
            messageId={messageId}
            content={content}
            prompt={prompt}
            rating={feedback}
            onRated={onFeedback}
          />
        )}
      </div>
    </div>
  );
}
