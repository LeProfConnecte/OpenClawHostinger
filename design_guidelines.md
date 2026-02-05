{
  "brand": {
    "name": "Moltbot Setup Shell",
    "attributes": ["serious", "trustworthy", "minimal", "developer-friendly", "quietly premium"],
    "voice": "precise, calm, action-oriented"
  },
  "typography": {
    "fonts": {
      "heading": "Space Grotesk",
      "body": "Fira Sans"
    },
    "import": [
      "https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap",
      "https://fonts.googleapis.com/css2?family=Fira+Sans:wght@400;500;600&display=swap"
    ],
    "apply": {
      "css": ":root { --font-heading: 'Space Grotesk', ui-sans-serif, system-ui; --font-body: 'Fira Sans', ui-sans-serif, system-ui; } body { font-family: var(--font-body); } .heading { font-family: var(--font-heading); }",
      "tailwind_classes": {
        "h1": "text-4xl sm:text-5xl lg:text-6xl font-semibold tracking-tight heading",
        "h2": "text-base sm:text-lg font-medium heading",
        "body": "text-sm sm:text-base",
        "small": "text-xs"
      }
    }
  },
  "color_system": {
    "tokens": {
      "--mb-bg": "#0f0f10",
      "--mb-bg-elev": "#141416",
      "--mb-fg": "#F2F3F5",
      "--mb-muted": "#9CA3AF",
      "--mb-border": "#1f2022",
      "--mb-accent": "#FF4500",
      "--mb-accent-600": "#E63E00",
      "--mb-accent-700": "#CC3700",
      "--mb-success": "#22c55e",
      "--mb-warning": "#f59e0b",
      "--mb-error": "#ef4444",
      "--mb-ring": "#FF4500"
    },
    "tailwind_alias": {
      "page_bg": "bg-[#0f0f10]",
      "card_bg": "bg-[#141416]",
      "text": "text-zinc-100",
      "muted_text": "text-zinc-400",
      "border": "border-[#1f2022]",
      "accent_bg": "bg-[#FF4500]",
      "accent_text": "text-white",
      "ring": "ring-[#FF4500]"
    },
    "contrast": "All text on #0f0f10 should be >= #e5e7eb (zinc-200) for 4.5:1. Accent #FF4500 over dark backgrounds passes."
  },
  "gradients_and_texture": {
    "note": "Follow Gradient Restriction Rule strictly. Use solid dark backgrounds for form areas; gradients only for page header halo/edges.",
    "examples": {
      "hero_edge_glow": "background: radial-gradient(60% 40% at 10% 0%, rgba(255,69,0,0.12), rgba(20,20,22,0) 60%), radial-gradient(50% 30% at 100% 10%, rgba(255,115,64,0.10), rgba(20,20,22,0) 60%), #0f0f10;",
      "fallback": "background: #0f0f10;"
    },
    "texture_css": ".texture-noise{ position:fixed; inset:0; pointer-events:none; background-image:url('https://images.unsplash.com/photo-1763386599791-fd86c07e1c86?auto=format&fit=crop&w=1200&q=60'); opacity:.08; mix-blend-mode:normal; }"
  },
  "layout": {
    "pattern": "Single-Column Layout with left-aligned content inside a centered container",
    "container": "container mx-auto px-4 sm:px-6 lg:px-8",
    "max_width": "max-w-lg",
    "sections": [
      "Top bar with minimal wordmark",
      "Card with Provider select, API key input, helper text, Start button",
      "Inline status area (progress) + error alert area",
      "Footer: docs/help links"
    ],
    "spacing": "Use generous vertical rhythm: space-y-6 at section level, space-y-4 within forms"
  },
  "components": [
    {
      "name": "ProviderSelect",
      "path": "./components/ui/select",
      "uses": "Select + SelectTrigger + SelectValue + SelectContent + SelectItem from shadcn",
      "testid": "provider-select",
      "notes": "Options: anthropic, openai. Required."
    },
    {
      "name": "ApiKeyInput",
      "path": "./components/ui/input",
      "uses": "Label + Input with type='password' and reveal toggle",
      "testid": "api-key-input",
      "notes": "Use monospace tracking-wider for keys; provide copy/paste and visibility toggle"
    },
    {
      "name": "StartButton",
      "path": "./components/ui/button",
      "testid": "start-moltbot-button",
      "notes": "Primary accent button. Loading state with spinner icon."
    },
    {
      "name": "StatusProgress",
      "path": "./components/ui/progress",
      "testid": "startup-progress",
      "notes": "Show stages: Validate -> Provision -> Launch -> Redirect"
    },
    {
      "name": "ErrorAlert",
      "path": "./components/ui/alert",
      "testid": "startup-error",
      "notes": "Red destructive style with remediation copy"
    },
    {
      "name": "Toaster",
      "path": "./components/ui/sonner",
      "testid": "global-toaster",
      "notes": "Use for ephemeral success/error notifications"
    },
    {
      "name": "Form",
      "path": "./components/ui/form",
      "notes": "Shadcn form primitives for validation messaging"
    },
    {
      "name": "Card",
      "path": "./components/ui/card",
      "notes": "Wrap setup controls in elevated surface"
    }
  ],
  "component_path": {
    "button": "./components/ui/button",
    "input": "./components/ui/input",
    "label": "./components/ui/label",
    "select": "./components/ui/select",
    "alert": "./components/ui/alert",
    "card": "./components/ui/card",
    "progress": "./components/ui/progress",
    "form": "./components/ui/form",
    "toaster": "./components/ui/sonner"
  },
  "micro_interactions": {
    "buttons": "Hover: bg-[#FF4500] -> bg-[#E63E00]; focus-visible:ring-2 ring-[#FF4500]; active: scale-98 via transform",
    "inputs": "Focus-visible:ring-2 ring-[#FF4500] ring-offset-0; subtle box-shadow: 0 0 0 2px rgba(255,69,0,.15)",
    "card_entry": "Fade+rise 200ms on mount using Framer Motion",
    "progress": "Animated bar width with ease-out; aria-live polite",
    "no_transition_all": true
  },
  "motion": {
    "library": "framer-motion",
    "install": "npm i framer-motion",
    "principles": ["fast feedback <=200ms", "ease-out for entrances, ease-in for exits", "reduce-motion: prefers-reduced-motion honors by disabling scale/translate"],
    "example": "<motion.div initial={{opacity:0,y:8}} animate={{opacity:1,y:0}} transition={{duration:0.2, ease:'easeOut'}} />"
  },
  "testing_ids": {
    "convention": "kebab-case role-based data-testid on all interactive/critical elements",
    "ids": [
      "provider-select",
      "api-key-input",
      "reveal-api-key-toggle",
      "start-moltbot-button",
      "startup-progress",
      "startup-status-text",
      "startup-error",
      "docs-link",
      "help-link",
      "control-ui-redirect"
    ]
  },
  "accessibility": {
    "rules": [
      "Labels and aria-describedby for inputs",
      "Visible focus states using accent ring",
      "Button text must not rely on color only",
      "Use role=alert for error banner and aria-live=polite for status",
      "Maintain 4.5:1 contrast for all text"
    ]
  },
  "responsive": {
    "mobile_first": true,
    "container": "max-w-lg w-full px-4 sm:px-6 py-8 sm:py-12",
    "stacking": "Form fields stack; footer switches to inline on md; space-y-6"
  },
  "image_urls": [
    {
      "url": "https://images.unsplash.com/photo-1763386599791-fd86c07e1c86?auto=format&fit=crop&w=1600&q=70",
      "usage": "subtle background noise overlay",
      "category": "setup_background",
      "alt": "Dark subtle noise texture"
    }
  ],
  "web_inspiration": {
    "sources": [
      "https://docs.molt.bot/web/control-ui",
      "https://www.soliddigital.com/blog/embrace-the-dark-side-10-inspiring-dark-website-design-examples",
      "https://saaslandingpage.com/tag/dark/"
    ],
    "applied": "Dark, security-focused onboarding with orange accent used sparingly; minimal distractions; clear progress and error handling"
  },
  "react_scaffolds": {
    "SetupPage.js": "import React, { useMemo, useState } from 'react'\nimport { Button } from './components/ui/button'\nimport { Input } from './components/ui/input'\nimport { Label } from './components/ui/label'\nimport { Card, CardHeader, CardTitle, CardContent, CardFooter } from './components/ui/card'\nimport { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from './components/ui/select'\nimport { Progress } from './components/ui/progress'\nimport { Toaster, toast } from './components/ui/sonner'\n\nexport default function SetupPage(){\n  const [provider, setProvider] = useState('')\n  const [apiKey, setApiKey] = useState('')\n  const [reveal, setReveal] = useState(false)\n  const [loading, setLoading] = useState(false)\n  const [error, setError] = useState('')\n  const [progress, setProgress] = useState(0)\n\n  const stageText = useMemo(() => {\n    if(progress < 10) return 'Waiting to start'\n    if(progress < 40) return 'Validating API key'\n    if(progress < 70) return 'Starting Moltbot services'\n    if(progress < 95) return 'Finalizing'\n    return 'Redirecting to Control UI'\n  }, [progress])\n\n  async function start(){\n    setError('')\n    if(!provider || !apiKey){\n      setError('Please choose a provider and enter an API key.')\n      return\n    }\n    try{\n      setLoading(true)\n      setProgress(20)\n      const res = await fetch('/api/moltbot/start', {\n        method: 'POST',\n        headers: { 'Content-Type': 'application/json' },\n        body: JSON.stringify({ provider, apiKey })\n      })\n      setProgress(55)\n      if(!res.ok){\n        const msg = await res.text()\n        throw new Error(msg || 'Startup failed')\n      }\n      const data = await res.json()\n      setProgress(92)\n      toast.success('Moltbot started')\n      // Redirect to real Moltbot Control UI\n      window.location.href = data.controlUrl || '/control'\n    }catch(e){\n      console.error(e)\n      setError(e.message || 'Unable to start Moltbot')\n      toast.error('Startup error')\n      setLoading(false)\n      setProgress(0)\n    }\n  }\n\n  return (\n    <div className=\"min-h-screen bg-[#0f0f10] text-zinc-100\">\n      <div className=\"texture-noise\" aria-hidden=\"true\"/>\n      <Toaster data-testid=\"global-toaster\" richColors position=\"top-center\" />\n\n      <header className=\"container mx-auto px-4 sm:px-6 py-6\">\n        <div className=\"max-w-lg\">\n          <h1 className=\"heading text-2xl sm:text-3xl font-semibold\">Moltbot Setup</h1>\n          <p className=\"text-zinc-400 mt-1\">Connect your LLM provider to start the Control UI.</p>\n        </div>\n      </header>\n\n      <main className=\"container mx-auto px-4 sm:px-6 pb-16\">\n        <Card className=\"max-w-lg border-[#1f2022] bg-[#141416]/95 backdrop-blur-sm\">\n          <CardHeader>\n            <CardTitle className=\"heading text-xl\">Provider & API Key</CardTitle>\n          </CardHeader>\n          <CardContent className=\"space-y-4\">\n            <div className=\"space-y-2\">\n              <Label htmlFor=\"provider\">LLM Provider</Label>\n              <Select onValueChange={setProvider} data-testid=\"provider-select\">\n                <SelectTrigger id=\"provider\" className=\"bg-[#0f0f10] border-[#1f2022] focus-visible:ring-[#FF4500]\">\n                  <SelectValue placeholder=\"Choose provider\" />\n                </SelectTrigger>\n                <SelectContent>\n                  <SelectItem value=\"anthropic\">Anthropic</SelectItem>\n                  <SelectItem value=\"openai\">OpenAI</SelectItem>\n                </SelectContent>\n              </Select>\n            </div>\n            <div className=\"space-y-2\">\n              <Label htmlFor=\"apiKey\">API Key</Label>\n              <div className=\"relative\">\n                <Input id=\"apiKey\" data-testid=\"api-key-input\" type={reveal ? 'text' : 'password'} value={apiKey} onChange={(e)=>setApiKey(e.target.value)} className=\"pr-24 tracking-wider bg-[#0f0f10] border-[#1f2022] focus-visible:ring-[#FF4500]\" placeholder=\"sk-... or api_...\" aria-describedby=\"apiKeyHelp\" />\n                <Button type=\"button\" variant=\"secondary\" data-testid=\"reveal-api-key-toggle\" onClick={()=>setReveal(r=>!r)} className=\"absolute right-2 top-1/2 -translate-y-1/2 h-8 px-3 text-xs\">{reveal ? 'Hide' : 'Show'}</Button>\n              </div>\n              <p id=\"apiKeyHelp\" className=\"text-xs text-zinc-400\">Your key is used only to start Moltbot; it is stored securely.</p>\n            </div>\n            {error ? (\n              <div role=\"alert\" data-testid=\"startup-error\" className=\"rounded-md border border-red-900/60 bg-red-950/40 text-red-300 px-3 py-2\">{error}</div>\n            ) : null}\n            {loading && (\n              <div className=\"space-y-2\">\n                <Progress value={progress} data-testid=\"startup-progress\" className=\"h-2\" />\n                <p className=\"text-xs text-zinc-400\" data-testid=\"startup-status-text\">{stageText}</p>\n              </div>\n            )}\n          </CardContent>\n          <CardFooter className=\"justify-between gap-3\">\n            <Button onClick={start} data-testid=\"start-moltbot-button\" disabled={loading} className=\"bg-[#FF4500] hover:bg-[#E63E00] text-white\">{loading ? 'Starting…' : 'Start Moltbot'}</Button>\n            <a href=\"https://docs.molt.bot/web/control-ui\" target=\"_blank\" rel=\"noreferrer\" className=\"text-xs text-zinc-400 hover:text-zinc-200\" data-testid=\"docs-link\">Docs</a>\n          </CardFooter>\n        </Card>\n        <p className=\"sr-only\" data-testid=\"control-ui-redirect\">Redirecting to Moltbot Control UI when startup completes</p>\n      </main>\n    </div>\n  )\n}\n",
    "css_utilities": {
      "noise": ".texture-noise{position:fixed;inset:0;background-image:url('https://images.unsplash.com/photo-1763386599791-fd86c07e1c86?auto=format&fit=crop&w=1200&q=60');opacity:.08;pointer-events:none;}",
      "button": ".btn-primary{ background:#FF4500; color:#fff; border-radius:10px; box-shadow:0 6px 18px rgba(255,69,0,.18);} .btn-primary:hover{ background:#E63E00;} .btn-primary:focus-visible{ outline:2px solid #FF4500; outline-offset:2px;}"
    }
  },
  "buttons_design": {
    "tone": "Professional / Corporate",
    "shape": "Medium radius (8-10px)",
    "variants": {
      "primary": "bg-[#FF4500] hover:bg-[#E63E00] text-white",
      "secondary": "bg-[#0f0f10] border border-[#1f2022] text-zinc-100 hover:bg-[#17181a]",
      "ghost": "text-zinc-300 hover:bg-white/5"
    },
    "sizes": { "sm": "h-8 px-3", "md": "h-10 px-4", "lg": "h-12 px-6" },
    "focus": "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#FF4500]"
  },
  "data_and_states": {
    "empty": "Show placeholder helper text and disabled Start until fields filled",
    "loading": "Disable inputs, show progress and status text",
    "error": "Inline alert, toast; do not shake inputs",
    "success": "Toast + redirect"
  },
  "libraries": {
    "primary": ["shadcn/ui (already included)", "sonner (included)", "framer-motion"],
    "optional": ["lottie-react for loader (optional)", "react-use for copy-to-clipboard"],
    "installs": [
      "npm i framer-motion",
      "npm i lottie-react",
      "npm i react-use"
    ]
  },
  "grid_and_spacing": {
    "grid": "Form stack, no sidebars. Keep line-length ~ 42–64ch",
    "spacing": "Use 2–3x comfortable spacing: section gap 24–32px, field gap 12–16px"
  },
  "dev_notes": {
    "js_only": true,
    "shadcn_only_for_primitives": true,
    "no_transition_all": true,
    "avoid_center_text_layout": true,
    "gradients_restriction": "Do not exceed 20% viewport; not on small UI; never purple/pink combos"
  },
  "instructions_to_main_agent": [
    "Add Google Fonts links in index.html and set CSS variables as specified.",
    "Ensure body has class 'dark' to use dark tokens in index.css; override tokens if needed with brand tokens.",
    "Create src/pages/SetupPage.js using the provided scaffold; wire routes to show this as the only custom page.",
    "Import shadcn components from ./components/ui/*.jsx as listed.",
    "Implement POST /api/moltbot/start in FastAPI to validate key, persist provider + encrypted key in MongoDB, start Moltbot, and return { controlUrl }.",
    "On success, redirect the browser to data.controlUrl (the official Moltbot Control UI).",
    "Add data-testid to every interactive element exactly as listed. Use kebab-case.",
    "Use Sonner toaster for ephemeral messages; mount once near app root.",
    "Respect Gradient Restriction Rule. Keep form backgrounds solid. Use texture overlay at low opacity only.",
    "Test mobile at 320px–390px; ensure controls are reachable and legible.",
    "If calendar/date inputs are ever added, use shadcn calendar component.",
    "Do not center-align global text; left-align paragraph and labels.",
    "No purple hues; accent is #FF4500 only."
  ]
}


General UI UX Design Guidelines  
    - You must **not** apply universal transition. Eg: `transition: all`. This results in breaking transforms. Always add transitions for specific interactive elements like button, input excluding transforms
    - You must **not** center align the app container, ie do not add `.App { text-align: center; }` in the css file. This disrupts the human natural reading flow of text
   - NEVER: use AI assistant Emoji characters like`🤖🧠💭💡🔮🎯📚🎭🎬🎪🎉🎊🎁🎀🎂🍰🎈🎨🎰💰💵💳🏦💎🪙💸🤑📊📈📉💹🔢🏆🥇 etc for icons. Always use **FontAwesome cdn** or **lucid-react** library already installed in the package.json

 **GRADIENT RESTRICTION RULE**
NEVER use dark/saturated gradient combos (e.g., purple/pink) on any UI element.  Prohibited gradients: blue-500 to purple 600, purple 500 to pink-500, green-500 to blue-500, red to pink etc
NEVER use dark gradients for logo, testimonial, footer etc
NEVER let gradients cover more than 20% of the viewport.
NEVER apply gradients to text-heavy content or reading areas.
NEVER use gradients on small UI elements (<100px width).
NEVER stack multiple gradient layers in the same viewport.

**ENFORCEMENT RULE:**
    • Id gradient area exceeds 20% of viewport OR affects readability, **THEN** use solid colors

**How and where to use:**
   • Section backgrounds (not content backgrounds)
   • Hero section header content. Eg: dark to light to dark color
   • Decorative overlays and accent elements only
   • Hero section with 2-3 mild color
   • Gradients creation can be done for any angle say horizontal, vertical or diagonal

- For AI chat, voice application, **do not use purple color. Use color like light green, ocean blue, peach orange etc**

</Font Guidelines>

- Every interaction needs micro-animations - hover states, transitions, parallax effects, and entrance animations. Static = dead. 
   
- Use 2-3x more spacing than feels comfortable. Cramped designs look cheap.

- Subtle grain textures, noise overlays, custom cursors, selection states, and loading animations: separates good from extraordinary.
   
- Before generating UI, infer the visual style from the problem statement (palette, contrast, mood, motion) and immediately instantiate it by setting global design tokens (primary, secondary/accent, background, foreground, ring, state colors), rather than relying on any library defaults. Don't make the background dark as a default step, always understand problem first and define colors accordingly
    Eg: - if it implies playful/energetic, choose a colorful scheme
           - if it implies monochrome/minimal, choose a black–white/neutral scheme

**Component Reuse:**
	- Prioritize using pre-existing components from src/components/ui when applicable
	- Create new components that match the style and conventions of existing components when needed
	- Examine existing components to understand the project's component patterns before creating new ones

**IMPORTANT**: Do not use HTML based component like dropdown, calendar, toast etc. You **MUST** always use `/app/frontend/src/components/ui/ ` only as a primary components as these are modern and stylish component

**Best Practices:**
	- Use Shadcn/UI as the primary component library for consistency and accessibility
	- Import path: ./components/[component-name]

**Export Conventions:**
	- Components MUST use named exports (export const ComponentName = ...)
	- Pages MUST use default exports (export default function PageName() {...})

**Toasts:**
  - Use `sonner` for toasts"
  - Sonner component are located in `/app/src/components/ui/sonner.tsx`

Use 2–4 color gradients, subtle textures/noise overlays, or CSS-based noise to avoid flat visuals.
