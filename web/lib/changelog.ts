export interface ChangelogEntry {
  /** Sortable id, also shown nowhere. Just needs to be unique and newest-first. */
  version: string;
  /** Human date shown in the UI, e.g. "Sep 13, 2026". */
  date: string;
  /**
   * When this entry actually shipped, ISO 8601 with offset. Powers the
   * "What's new" modal's expanded timeline view (real ship time next to
   * the version badge, so same-day releases like "-2"/"-3" read in order).
   * Backfilled from the git commit that last touched each entry below;
   * never hand-wave a time for a new entry, pull it from `git log` once
   * the change is actually committed.
   */
  timestamp?: string;
  /** Short, plain-language, user-facing bullets. See .cursor/rules/changelog.mdc. */
  items: string[];
}

/**
 * User-facing changelog, newest entry first. Every deploy that changes what
 * a user can see or do should add (or extend) an entry here. See
 * .cursor/rules/changelog.mdc for the house style.
 */
export const CHANGELOG: ChangelogEntry[] = [
  {
    version: "2026.09.16-8",
    date: "Sep 16, 2026",
    items: [
      "The upgrade preview now plays short demo videos on the first two slides, in a larger modal.",
    ],
  },
  {
    version: "2026.09.16-7",
    date: "Sep 16, 2026",
    items: [
      "Build answers now call the top pick overall, not overlay.",
      "Named shiny sets now use RealmEye item pages, so a bow is not called a sword, and Crown means The Forgotten Crown.",
    ],
  },
  {
    version: "2026.09.16-6",
    date: "Sep 16, 2026",
    items: [
      "Build advice now leads with a short player-confirmed base for each weapon type, robes, leather, and rings.",
      "Unusual class and stat builds now stack that stat from the class wiki table unless Umi or RealmShark already has that full set.",
      "Samurai and Kensei Dexterity or Vitality sets now name Tools of the Tarnished with Fungal Breastplate.",
    ],
  },
  {
    version: "2026.09.16-5",
    date: "Sep 16, 2026",
    items: [
      "Build alternatives now come from UmiEnjoyers best-in-slot lists for every slot, not just armor and rings.",
      "Attack robe builds name Vesture of Duality next to Diplomatic Robe, and skip filler T7 robes.",
      "Umi best-in-slot now reads every build tab, like Speed Wizard, not only General.",
    ],
  },
  {
    version: "2026.09.16-4",
    date: "Sep 16, 2026",
    items: [
      "The upgrade popup shows again whenever you try an in-depth response after you are out for the day.",
    ],
  },
  {
    version: "2026.09.16-3",
    date: "Sep 16, 2026",
    items: [
      "Outfit follow-ups, like asking for the small cloth too, stay on the free visualizer.",
      "Looking up a player no longer spends an in-depth response.",
      "The free counter now says in-depth responses.",
      "When those run out, leftover suggestions sit above the message box until you hide them, and the tab title is Your AI Guide for RotMG.",
    ],
  },
  {
    version: "2026.09.16-2",
    date: "Sep 16, 2026",
    items: [
      "Answers that do not use the AI no longer count toward your daily messages, even before you sign in.",
      "The free counter now says in-depth prompts, so lookups that skip the AI stay free.",
      "In-depth answers now lead with the recommended set and one RealmShark top 5, not a dump of every source.",
      "When in-depth prompts run out, lookups still work, and the upgrade popup only shows once.",
    ],
  },
  {
    version: "2026.09.16",
    date: "Sep 16, 2026",
    items: [
      "Attack Bard recommendations now follow the real best set, not just the wiki max-stat row.",
      "Common nicknames like cbow, lbow, dbow, triangle, and lean crown now resolve to the real items.",
      "Kagenohikari is always listed with Crown, Lean, and Gemstone when talking about rings.",
      "Small typos in class and dungeon names still resolve, and cbow vs lbow awakening now compares both.",
    ],
  },
  {
    version: "2026.09.15",
    date: "Sep 15, 2026",
    timestamp: "2026-09-15T10:49:50-07:00",
    items: [
      "On phones, sidebar suggestion prompts start hidden, and that hide or show choice is remembered next time.",
      "The menu now has a New chat button above your chat list.",
      "The in-game name field now tells you to enter your IGN to find your pet.",
      "Finding your pet by IGN is much faster, and shows a clear message if your pet yard is hidden.",
      "Fixed a rare case where looking up the same player twice in a row could show a plain text summary with no character card and no explanation.",
      "Listing out a shiny loadout (weapon, ability, armor, ring) now renders the visual set preview even without saying \"set\" or \"loadout.\"",
      "Item names now resolve even with a small typo, and rarity words like rare, legendary, or uncommon no longer confuse the lookup.",
    ],
  },
  {
    version: "2026.09.14-2",
    date: "Sep 14, 2026",
    timestamp: "2026-09-14T23:15:37-07:00",
    items: [
      "Phones now show the chat first, with a full-screen menu behind a button in the top left.",
      "The message box stays on screen above the Safari toolbar, so you no longer have to scroll to type.",
    ],
  },
  {
    version: "2026.09.14",
    date: "Sep 14, 2026",
    timestamp: "2026-09-14T22:37:35-07:00",
    items: [
      "Chat answers are grounded in real wiki data again, across every kind of question.",
      "Dungeon guides and the skin/outfit visualizer are back to full strength after a rough patch.",
      "Skin visualizer follow-ups, like correcting a name or asking for just the shiny or divine version, work more reliably.",
      "Full outfit and set requests load correctly instead of spinning forever.",
      "Enchanting advice no longer suggests rare enchants that only fit one specific item.",
      "Asking about an item's enchant right after a build question now gets a real answer instead of repeating the build.",
      "Follow-up questions about a completely different item no longer get answered with your last unrelated build.",
      "Signed-in chats now stay saved to your account, even if you're in a private/incognito window that later closes.",
      "Your in-game name and pet companion now show up in the sidebar automatically after signing in, on any device.",
      "Your free daily messages now reset at the same time each day for everyone, instead of depending on when you first messaged.",
      "Tapping the sides of the upgrade screen now flips between slides, like a story.",
      "Asking about an item in the same sentence as an unrelated follow-up question now correctly shows that item, instead of a broken result.",
      "Asking for a shiny/divine build by class and stat (like \"attack huntress\" or \"a set for dex huntress\") no longer errors out trying to look it up as a single item.",
      "Asking to see a full shiny/divine build by class and stat now shows the actual recommended weapon, ability, armor, and ring as a loadout, instead of a wall of text.",
    ],
  },
  {
    version: "2026.09.13",
    date: "Sep 13, 2026",
    timestamp: "2026-09-13T16:49:30-07:00",
    items: [
      "Pro gets more chat included every month, plus an optional pay-as-you-go option so you're never stuck waiting.",
      "Checkout now offers Link, so returning Stripe customers can pay without retyping their card.",
      "Ask for enchants on an item and RealmPal now figures out the build that fits it (like Attack for a +20 Attack item) instead of listing every option.",
      "Drops, best gear, and build guides now answer instantly.",
      "You can now see exactly when your free daily messages reset.",
      "Billing and usage now live in the account menu.",
      "Daily quests now live in chat. Finish today's set for an extra message.",
      "Each daily quest now shows today's dungeon portal, an eyeball for player lookup, or a shiny item, all the same size.",
      "Quest icons stay visible when a dungeon name is long.",
      "Sign in and registration no longer spin forever if the server is slow. You'll see a clear message and can just try again.",
      "Looking up a player, item, or dungeon now shows a clear message instead of spinning forever if it's taking too long.",
      "Dungeon portals show up again after you refresh daily quests.",
      "The Shatters quest now shows the real dungeon portal, not the ice portal inside it.",
      "Hardmode Shatters again uses the purple Source dome as its portal.",
      "The shiny star only shows when that item actually has a shiny version.",
      "The top bar is now messages left, What’s new, Quests, Sign in, then your profile.",
      "The Quests button in the top bar shows your daily progress again.",
      "The top-right buttons now sit on their own tab so they don't cover your chat.",
      "The free-message popup now tells you exactly how many free messages you have left, instead of always showing a countdown.",
      "Creating an account now loads your pet into the sidebar right away.",
      "Starting a chat from a daily quest or a suggested question now shows up in your chat list like any other chat.",
      "Fixed a rare case where the daily quest bonus message could disappear or reset too early.",
      "Pro members can now manage or cancel their subscription right from the billing menu, no more emailing support.",
      "The Quests progress bar sits under the Quests label.",
      "Hovering a shiny quest item now shows its name instead of clipping it.",
      "Dungeon guides no longer stall or drop item cards after a long drop list.",
      "The quests refresh button now picks a new dungeon and a new shiny item.",
      "Refreshing quests now swaps the shiny item art instead of leaving the last one stuck.",
      "The shiny quest now uses the same divine glow and diamonds as a visualized set.",
      "Dungeon quest names no longer include leftover wiki text.",
      "Dungeon guides now show the real dungeon portal, not the ice portal inside The Shatters.",
      "The daily quests window opens again.",
      "Finished daily quests stay clickable, with a pointer cursor on hover.",
      "Click any item sprite to zoom it full size. Tap the backdrop to close.",
      "The message reset countdown is now easier to spot in mustard yellow.",
      "Item zoom now keeps divine glow, shiny stars, and stats, with a link back to RealmEye.",
      "Dungeon guides now show the right difficulty graves and less repeated wiki text.",
      "Layout maps in dungeon guides are sized down so they do not blow up the chat.",
      "Drop icons in dungeon guides are a bit larger.",
      "The top bar buttons have a little more breathing room.",
      "Billing now shows a usage progress bar with a percentage, above your plan.",
      "Pro users can set a pay-as-you-go spending limit ($20, $50, $100, or custom) from Billing.",
      "When your included replies run out, the paywall and Billing both let you manage your spending limit.",
      "Skin preview questions like 'what does X look like with Y cloth' now resolve the skin name correctly.",
      "Skin previews render instantly without calling Claude, and show a clear message if RealmEye cannot composite the outfit.",
      "Clickable buttons and links now show the pointer cursor consistently.",
      "The sidebar account row now shows your IGN with your email underneath.",
      "Your sidebar pet now saves with your account and shows up everywhere you sign in.",
      "Skin preview follow-ups like 'what does it look like with small black dye' keep the same skin from earlier in the chat.",
      "The skin preview card applies one cloth or dye to both clothing and accessory.",
      "Saying switch in a skin preview now swaps the clothing and accessory instantly.",
      "Swapping a cloth preview turns Large cloth into Small cloth on the other slot.",
      "Signed-in accounts no longer use a chat message on instant answers like drops and skin previews.",
      "Dungeon guides still use the RealmEye writeup, without leftover wiki banners and duplicate pages.",
      "Dungeon cards, item sprites, and skin previews stay when you reopen a chat.",
      "The Quests tab now shows your daily progress as a small percentage beside the bar.",
      "Build guides use the stronger model on the first ask, then replay instantly from your saved answer.",
      "Build prompts now understand common class nicknames like pally, trix, sorc, hunt, and wiz.",
      "Your chats and daily quest progress stay with your account when you sign out and back in.",
      "Clicking today's shiny quest now shows that item right away.",
      "Your top pet is now the one with the highest RealmEye ability levels, not the first pet in the yard.",
      "Click a character, item, or skin card to see a larger copy of the whole card in the center of the screen. Gear icons and links on the card still work as their own clicks.",
    ],
  },
];

/** Newest version, derived automatically. Don't hand-edit this. */
export const LATEST_VERSION = CHANGELOG[0]?.version ?? "";

const STORAGE_KEY = "realm_pal_changelog_seen";

/** True if the visitor hasn't seen the latest changelog entry yet. */
export function hasUnseenChangelog(): boolean {
  if (typeof window === "undefined" || !LATEST_VERSION) return false;
  try {
    return window.localStorage.getItem(STORAGE_KEY) !== LATEST_VERSION;
  } catch {
    return false;
  }
}

/** Marks the latest changelog entry as seen, so the popup won't nag again. */
export function markChangelogSeen(): void {
  if (typeof window === "undefined" || !LATEST_VERSION) return;
  try {
    window.localStorage.setItem(STORAGE_KEY, LATEST_VERSION);
  } catch {
    // Private mode / storage disabled. Not worth failing over.
  }
}
