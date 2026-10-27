---
name: Warhammer Agent handbook
description: Local English rules and datasheet chat inspired by the supplied Core Rules PDF.
colors:
  paper: "#F1F0EA"
  rule-box: "#E4E0D5"
  ink: "#242522"
  sidebar: "#232722"
  sidebar-surface: "#33382F"
  sidebar-text: "#EFEEE5"
  gold: "#8A7D40"
  sidebar-gold: "#C6B775"
  source-green: "#245C52"
  error-red: "#9C302B"
  border: "#B8B4A7"
typography:
  heading:
    fontFamily: '"Arial Narrow", "Helvetica Neue", Arial, sans-serif'
    fontSize: "clamp(2rem, 4vw, 3rem)"
    fontWeight: 800
    lineHeight: 1.08
    letterSpacing: "-0.025em"
  answer:
    fontFamily: 'Georgia, "Times New Roman", serif'
    fontSize: "1.075rem"
    lineHeight: 1.7
rounded:
  control: "4px"
spacing:
  small: "12px"
  normal: "16px"
  section: "24px"
---

## Overview

**Creative North Star: "A readable rules handbook."**

Adapt the supplied Core Rules PDF's pale reading pages, compact black headings,
neutral rule boxes and restrained colored markers. The dark cover contributes a
charcoal sidebar and antique-gold details. The interface remains an English chat
tool: native controls, readable answers and inspectable references come first.

## Colors

Native tokens live in `.streamlit/config.toml`; narrowly scoped composition and
contrast overrides live in `src/warhammer_agent/ui.css`. Paper and ink carry the
conversation; gold marks the page and session action. Green identifies sources
and completed answers, red identifies errors. The gold session button has dark
text, not white. Main captions use #5C5E54; sidebar captions use #C4C8BA.

## Typography

Use compact uppercase lettering only for the product heading. Answer prose and
list/table bodies use a serif stack, while controls and source metadata remain
sans serif. System font stacks are an explicit project constraint; do not extract
PDF fonts or fetch web fonts. At widths below 640px, answer prose becomes 1rem.

## Layout

The native centered Streamlit layout limits the reading measure. Keep the sidebar
for session controls and folded settings. Present three stacked example questions
only before conversation starts. On small screens the native sidebar collapses;
answers, tables and references must remain within the viewport. Long source paths
wrap; code can scroll horizontally within its own block.

## Shapes

Use quiet 1px borders and small native control radii. The title has a 3px gold
upper rule and a 1px lower divider. No decorative shadows, textures or animation.

## Components

- Google API key: visible password field with an AI Studio link and explicit clear action. Empty keys disable chat and examples; keys stay in session memory, never theme/configuration or run records.
- New conversation: prominent gold sidebar action; rotates the session ID and clears the visible history without resetting the selected model.
- Example questions: Core Rules, Datasheets, and Rules + datasheets; each submits through the same Agent flow as the chat input.
- Answer: native accessible chat message with book icon, readable prose and inline citations.
- Sources: collapsed expander, separating PDF rules (title and physical pages) from SQL sources (database and tables).
- Run details: collapsed diagnostic expander; errors remain visible outside it and survive reruns.

## Do's and Don'ts

- Keep all interaction and documentation in English.
- Preserve native focus, keyboard controls, table semantics and sidebar navigation.
- Keep sources separate from diagnostic details.
- Do not use full-page illustrations, military emblems or heavy paper textures.
- Do not style Streamlit's generated Emotion class names or hide native controls.
- Do not change retrieval, SQL, model defaults or persistent sessions for styling.
