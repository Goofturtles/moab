// SAMPLE DATA. Every company and person in this file is made up.
// It stands in for what only Spotify has: its customer records (HubSpot),
// signed papers (Google Drive, DocuSign), call notes (Gong) and job-change alerts.
// Company names that appear on the real Backstage adopters list (for example bol.com)
// are only used as someone's past employer, never given made-up history.

window.SAMPLE = {
  today: "2026-10-18",

  // Upcoming calls on Chris's calendar.
  invites: [
    {
      id: "northwind",
      title: "Discovery call: Northwind Freight and Spotify Portal",
      when: "Tue Oct 20, 10:00 to 10:45 ET",
      company: "Northwind Freight",
      meetingCode: "nwf-portal-call", // made up; inside Google Meet the panel matches the real meeting code to a call
      attendees: [
        { name: "Priya Raman", email: "priya.raman@northwindfreight.example" },
        { name: "Marcus Bell", email: "marcus.bell@northwindfreight.example" },
        { name: "Elena Cruz", email: "elena.cruz@northwindfreight.example" },
      ],
      notes: "Marcus says Backstage upgrades are eating his team's time. They also looked at Port last quarter.",
      versionFile: '{\n  "version": "1.24.0"\n}',
      backstageSince: 2021,
      afterNotes:
        "Priya wants a one-month pilot. Elena asked for the latest security pack before procurement. " +
        "Marcus said Tom Hughes from their security team will join the next call. Budget is approved for Q1.",
    },
    {
      id: "quillstack",
      title: "Intro: Quillstack and Spotify (AI coding agents)",
      when: "Wed Oct 21, 14:00 to 14:30 ET",
      company: "Quillstack",
      meetingCode: "qsk-intro-call",
      attendees: [
        { name: "Sam Okafor", email: "sam@quillstack.example" },
        { name: "Dana Li", email: "dana.li@quillstack.example" },
      ],
      notes: "Their engineers use Claude Code and Codex every day. They want their AI agents to know who owns what.",
      versionFile: "",
      backstageSince: null,
      afterNotes:
        "Sam wants to try Xirp with two teams first. Dana asked how Xirp connects to Portal later. " +
        "No NDA yet. Follow up next week.",
    },
    {
      id: "rookery",
      title: "Experimentation chat: Rookery Retail and Spotify Confidence",
      when: "Thu Oct 22, 11:00 to 11:45 ET",
      company: "Rookery Retail",
      meetingCode: "rky-confidence",
      attendees: [
        { name: "Michael Tran", email: "michael.tran@rookery.example" },
        { name: "Ava Brooks", email: "ava.brooks@rookery.example" },
      ],
      notes: "They run A/B tests on their checkout page. They use LaunchDarkly for feature flags today.",
      versionFile: "",
      backstageSince: null,
      afterNotes:
        "Ava wants to see how Confidence measures results. Michael asked about pricing for 40 engineers. " +
        "Security review needed before a pilot.",
    },
  ],

  // What Spotify's customer records would say about each person (stands in for HubSpot and LinkedIn Sales Navigator).
  people: {
    "priya.raman@northwindfreight.example": {
      photo: "https://images.pexels.com/photos/29811345/pexels-photo-29811345.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "VP, Platform Engineering", startedAt: "2026-05", previous: "bol.com",
      previousRole: "Head of Developer Experience", known: false,
      note: "",
    },
    "marcus.bell@northwindfreight.example": {
      photo: "https://images.pexels.com/photos/37148308/pexels-photo-37148308.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "Staff Engineer, Developer Experience", startedAt: "2022-03", previous: "", known: true,
      note: "Runs Northwind's Backstage. Came to Portal Office Hours in March 2026.",
    },
    "elena.cruz@northwindfreight.example": {
      photo: "https://images.pexels.com/photos/30004323/pexels-photo-30004323.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "Director, Procurement", startedAt: "2019-08", previous: "", known: false,
      note: "First time on a call with Spotify.",
      // What invitee research looks like once MOAB has looked a new guest up (made up, like everything here).
      research: {
        status: "done", note: "", found: "auto", foundAt: "2026-10-19T14:00:00+00:00", confidence: "medium",
        title: "Director, Procurement", team: "Procurement", seniority: "director", tenure: "about 7 years", relationship: "employee",
        sources: [{ url: "https://northwindfreight.example/about/leadership", label: "Northwind Freight leadership page" }],
        local: { company: "Northwind Freight", adopter: false, metBefore: false, lastMet: "" },
        // The profile MOAB's research builds (server.py's records.people[email].profile, contract v2). Made up, with made-up sources.
        profile: {
          v: 2, name: "Elena Cruz", at: "2026-10-19T14:00:00+00:00", confidence: "medium",
          summary: { text: "Elena Cruz runs procurement at Northwind Freight, where she has worked for about seven years. Her team signs off software purchases and vendor security reviews.", src: [0, 1] },
          now: [
            { text: "Director of Procurement: her team handles every software purchase above the approval limit.", src: [0] },
            { text: "Brought in a vendor security questionnaire that every new software supplier must answer before a contract.", src: [1] },
          ],
          past: [
            { role: "Senior Buyer, IT", org: "Calder Logistics", when: "2014 - 2019", src: [2],
              points: [{ text: "Bought cloud and software contracts for a 3,000-person logistics company.", src: [2] }] },
          ],
          education: [],
          work: [{ text: "Talk: \"Buying software security will approve\", Example Procurement Summit 2025.", src: [3] }],
          forCall: [
            { text: "She asks every new supplier for the security questionnaire first: offer to walk her through Spotify's security pack.", src: [1] },
            { text: "She spoke about getting software past security review; ask what slowed her last purchase down.", src: [3] },
          ],
          sources: [
            { url: "https://northwindfreight.example/about/leadership", label: "Northwind Freight leadership page" },
            { url: "https://northwindfreight.example/suppliers/security", label: "Northwind Freight supplier security requirements" },
            { url: "https://calderlogistics.example/news/2017-it-buying-team", label: "Calder Logistics news: meet the IT buying team" },
            { url: "https://procurementsummit.example/2025/speakers/elena-cruz", label: "Example Procurement Summit 2025 speaker page" },
          ],
        },
      },
    },
    "sam@quillstack.example": {
      photo: "https://images.pexels.com/photos/20374423/pexels-photo-20374423.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "CTO and co-founder", startedAt: "2023-01", previous: "Helix Health",
      previousRole: "Engineering Manager", known: true,
      note: "Talked to Spotify in January 2026 (see history).",
      research: {
        status: "done", note: "", found: "confirmed", foundAt: "2026-10-19T14:05:00+00:00", confidence: "high",
        title: "CTO and co-founder", team: "Engineering", seniority: "executive", tenure: "almost 4 years", relationship: "employee",
        sources: [], local: { company: "Quillstack", adopter: false, metBefore: true, lastMet: "Jan 14, 2026" },
        profile: {
          v: 2, name: "Sam Okafor", at: "2026-10-19T14:05:00+00:00", confidence: "high",
          summary: { text: "Sam Okafor co-founded Quillstack in 2023 and runs its engineering team as CTO. Before that he spent six years at Helix Health, the last three managing its platform team.", src: [0, 1] },
          now: [
            { text: "CTO of Quillstack: owns engineering, the platform, developer tooling and security for about 80 engineers.", src: [0] },
            { text: "Set the rule that every service has a named owning team, kept in CODEOWNERS files.", src: [2] },
            { text: "Rolled Claude Code and Codex out to every engineer in early 2026.", src: [2, 3] },
            { text: "Hiring fast: 31 open engineering roles on Quillstack's careers page.", src: [4] },
          ],
          past: [
            { role: "Engineering Manager, Platform", org: "Helix Health", when: "2019 - 2022", src: [1],
              points: [{ text: "Ran the team that built Helix Health's internal developer portal.", src: [1] },
                { text: "Moved 120 services onto one shared build pipeline.", src: [5] }] },
            { role: "Senior Software Engineer", org: "Helix Health", when: "2016 - 2019", src: [1],
              points: [{ text: "Built the scheduling service behind Helix Health's patient app.", src: [1] }] },
            { role: "Software Engineer", org: "Fernhill Data", when: "2013 - 2016", src: [6], points: [] },
          ],
          education: [{ text: "BSc, Computer Science (as listed on his speaker page).", src: [1] }],
          work: [
            { text: "Talk: \"Who owns this service? Ownership for AI agents\", Example Conf 2026.", src: [3] },
            { text: "Post: \"How we gave our coding agents a map of the codebase\", Quillstack engineering blog.", src: [2] },
            { text: "Maintains codeowners-lint, an open-source checker for CODEOWNERS files.", src: [7] },
          ],
          forCall: [
            { text: "His agents read owners from CODEOWNERS files today; ask what they can't find there, like who decided what and why.", src: [2, 3] },
            { text: "He built a developer portal at Helix Health, so he knows the upkeep; Xirp now, with a path to Portal, avoids that.", src: [1] },
          ],
          sources: [
            { url: "https://quillstack.example/about", label: "Quillstack: about us" },
            { url: "https://conf.example.com/2026/speakers/sam-okafor", label: "Example Conf 2026 speaker page" },
            { url: "https://quillstack.example/blog/agents-codebase-map", label: "Quillstack engineering blog: a map of the codebase for our agents" },
            { url: "https://conf.example.com/2026/talks/ownership-for-ai-agents", label: "Example Conf 2026 talk: Who owns this service?" },
            { url: "https://quillstack.example/careers", label: "Quillstack careers" },
            { url: "https://helixhealth.example/engineering/one-pipeline", label: "Helix Health engineering blog: one pipeline for 120 services" },
            { url: "https://fernhilldata.example/about/team-2015", label: "Fernhill Data team page (2015)" },
            { url: "https://code.example.com/sokafor/codeowners-lint", label: "codeowners-lint repository" },
          ],
        },
      },
    },
    "dana.li@quillstack.example": {
      photo: "https://images.pexels.com/photos/20051635/pexels-photo-20051635.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "Head of Developer Productivity", startedAt: "2026-10", previous: "Lumen Air",
      previousRole: "Platform Lead", known: true,
      note: "Was your strongest supporter there.",
      research: {
        status: "done", note: "", found: "confirmed", foundAt: "2026-10-19T14:06:00+00:00", confidence: "high",
        title: "Head of Developer Productivity", team: "Developer Productivity", seniority: "head", tenure: "joined this month", relationship: "employee",
        sources: [], local: { company: "Quillstack", adopter: false, metBefore: true, lastMet: "Aug 20, 2026" },
        profile: {
          v: 2, name: "Dana Li", at: "2026-10-19T14:06:00+00:00", confidence: "high",
          summary: { text: "Dana Li joined Quillstack this month to lead developer productivity. She spent seven years at Lumen Air, the last five leading the platform team that ran its developer portal.", src: [0, 1] },
          now: [
            { text: "Head of Developer Productivity at Quillstack: build tooling, CI and the internal developer experience.", src: [0] },
            { text: "Says her first goal is to measure how long a new engineer takes to ship their first change.", src: [0, 2] },
          ],
          past: [
            { role: "Platform Lead", org: "Lumen Air", when: "2021 - 2026", src: [1],
              points: [{ text: "Led the platform team that ran Lumen Air's internal developer portal.", src: [1] },
                { text: "Cut new-engineer setup from two weeks to two days.", src: [3] }] },
            { role: "Senior Engineer, Developer Tools", org: "Lumen Air", when: "2019 - 2021", src: [1],
              points: [{ text: "Built the service templates every Lumen Air team starts from.", src: [3] }] },
            { role: "Software Engineer", org: "Tessellate Systems", when: "2015 - 2019", src: [5], points: [] },
          ],
          education: [{ text: "MEng, Software Engineering (as listed on her speaker page).", src: [4] }],
          work: [
            { text: "Talk: \"Two weeks to two days: onboarding with a developer portal\", Example Conf 2025.", src: [4] },
            { text: "Post: \"What I look for in a platform team\", on her engineering blog.", src: [2] },
          ],
          forCall: [
            { text: "She ran a developer portal at Lumen Air; ask what she wants to keep and what she never wants to maintain again.", src: [1, 4] },
            { text: "She is measuring time to first change: show how Portal and Xirp shorten it.", src: [0, 2] },
          ],
          sources: [
            { url: "https://quillstack.example/blog/welcome-dana", label: "Quillstack blog: welcome, Dana" },
            { url: "https://lumenair.example/engineering/team", label: "Lumen Air engineering team page" },
            { url: "https://danali.example/posts/platform-teams", label: "Dana Li's engineering blog: What I look for in a platform team" },
            { url: "https://lumenair.example/engineering/onboarding", label: "Lumen Air engineering blog: two days to a first commit" },
            { url: "https://conf.example.com/2025/speakers/dana-li", label: "Example Conf 2025 speaker page" },
            { url: "https://tessellate.example/about/team-2018", label: "Tessellate Systems team page (2018)" },
          ],
        },
      },
    },
    "michael.tran@rookery.example": {
      photo: "https://images.pexels.com/photos/31268612/pexels-photo-31268612.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "Head of Growth Engineering", startedAt: "2026-07", previous: "Helix Health",
      previousRole: "Senior Engineer, Experimentation", known: false,
      note: "",
    },
    "ava.brooks@rookery.example": {
      photo: "https://images.pexels.com/photos/30468665/pexels-photo-30468665.jpeg?auto=compress&cs=tinysrgb&w=320&h=320&fit=crop", // stock photo (Pexels licence), see CREDITS.md
      title: "Product Director, Checkout", startedAt: "2021-04", previous: "", known: false,
      note: "",
      // What research says when the web has nothing about someone's work (it never asks you to look them up).
      research: {
        status: "unknown", note: "MOAB searched 12 sites and found no public work information about them.", found: "", foundAt: "2026-10-19T14:08:00+00:00", confidence: "",
        title: "", team: "", seniority: "", tenure: "", relationship: "", sources: [],
        local: { company: "Rookery Retail", adopter: false, metBefore: false, lastMet: "" },
      },
    },
  },

  // "Mentioned on the call" in the demo: a made-up transcript of the Northwind call and what MOAB would find in it.
  // Grace Ito stands in for someone already in Spotify's records; Tom Hughes for someone found on the web (example.com-style sources);
  // John (a first name and a team, "from product managing") for someone found automatically from one clear match.
  // Companies: Brightwave Systems (the call explains the relation right after) and Harborline Labs (no explanation, so found on the web).
  mentionSample: {
    callId: "northwind",
    file: "northwind-call.vtt",
    transcript:
      "WEBVTT\n\n00:12:41.000 --> 00:12:47.000\n<v Priya Raman>Anything over fifty thousand goes to Grace Ito in finance, so she should see the quote.</v>\n\n"
      + "00:18:05.000 --> 00:18:11.000\n<v Marcus Bell>Tom Hughes from our security team will join the next call for the security review.</v>\n\n"
      + "00:21:30.000 --> 00:21:36.000\n<v Priya Raman>I'll have to talk with John about that from product managing. He owns the roadmap.</v>\n\n"
      + "00:24:02.000 --> 00:24:09.000\n<v Marcus Bell>Most of our alerts still go through Brightwave Systems. They're our vendor for logging.</v>\n\n"
      + "00:27:15.000 --> 00:27:19.000\n<v Priya Raman>Harborline Labs keeps asking about the pilot too.</v>\n",
    items: [
      {
        id: "sample000001", name: "Grace Ito", role: "finance", kind: "known", count: 1, source: "upload", status: "known", note: "",
        quote: { text: "Anything over fifty thousand goes to Grace Ito in finance, so she should see the quote.", speaker: "Priya Raman", time: "12:41" },
        person: { name: "Grace Ito", title: "Head of Finance", team: "Finance", relationship: "employee", confidence: "", why: "", from: "Sample data", sources: [],
          met: { known: true, last: "Feb 11, 2025" } },
        candidates: [], confirmed: false, added: false, hubspot: "", connected: true,
        explain: { kind: "person", name: "Grace Ito", title: "Head of Finance", type: "employee", typeLabel: "Employee", label: "finance", team: "Finance",
          explanation: [], since: null, evidence: [], said: null, mention: null, confidence: "", likely: false,
          found: { call: "Northwind Freight", title: "Discovery call: Northwind Freight and Spotify Portal", via: "your transcript", time: "12:41", at: "2026-10-21T15:30:00+00:00", how: "Known to MOAB" } },
      },
      {
        id: "sample000002", name: "Tom Hughes", role: "security", kind: "full", count: 1, source: "upload", status: "found", note: "",
        quote: { text: "Tom Hughes from our security team will join the next call for the security review.", speaker: "Marcus Bell", time: "18:05" },
        person: { name: "Tom Hughes", title: "Security Engineering Manager", team: "Security", seniority: "manager", relationship: "employee", confidence: "medium",
          why: "Named as Northwind Freight's security engineering manager on its engineering blog.", from: "Web",
          sources: [{ url: "https://northwindfreight.example/blog/zero-trust-rollout", label: "Northwind Freight engineering blog" },
            { url: "https://conf.example.com/2026/speakers/tom-hughes", label: "Example Conf speaker page" }],
          met: { known: true, last: "" } },
        candidates: [], confirmed: false, added: false, hubspot: "", autoFound: true, connected: true,
        explain: { kind: "person", name: "Tom Hughes", title: "Security Engineering Manager", type: "employee", typeLabel: "Employee", label: "security", team: "Security",
          explanation: [{ text: "Tom Hughes manages Northwind Freight's security engineering team, which ran its zero-trust rollout.", sources: [0] },
            { text: "He spoke about that rollout at Example Conf in 2026.", sources: [1] }],
          since: null, said: null, mention: null, confidence: "medium", likely: false,
          evidence: [{ url: "https://northwindfreight.example/blog/zero-trust-rollout", label: "Northwind Freight engineering blog", date: "2026-03-12",
              quote: "Tom Hughes, who manages our security engineering team, led the zero-trust rollout across every warehouse." },
            { url: "https://conf.example.com/2026/speakers/tom-hughes", label: "Example Conf speaker page", date: "2026-05",
              quote: "Tom Hughes, Security Engineering Manager at Northwind Freight, on rolling out zero trust." }],
          found: { call: "Northwind Freight", title: "Discovery call: Northwind Freight and Spotify Portal", via: "your transcript", time: "18:05", at: "2026-10-21T15:30:00+00:00", how: "Found on the web" } },
      },
      {
        id: "sample000003", name: "John", role: "product management", kind: "partial", count: 1, source: "upload", status: "found", note: "",
        quote: { text: "I'll have to talk with John about that from product managing.", speaker: "Priya Raman", time: "21:30" },
        said: { label: "owns the roadmap", team: "", relationship: "", said: "He owns the roadmap.", speaker: "Priya Raman", time: "21:30" },
        person: { name: "John Reyes", title: "Group Product Manager", team: "Product Management", seniority: "manager", relationship: "employee", confidence: "high",
          why: "The only John on Northwind Freight's product team in public sources.", from: "Web",
          sources: [{ url: "https://northwindfreight.example/blog/roadmap-2026", label: "Northwind Freight product blog" },
            { url: "https://conf.example.com/2026/speakers/john-reyes", label: "Example Conf speaker page" }],
          met: { known: true, last: "" } },
        candidates: [], confirmed: false, added: false, hubspot: "", autoFound: true, connected: true,
        explain: { kind: "person", name: "John Reyes", title: "Group Product Manager", type: "employee", typeLabel: "Employee", label: "owns the roadmap", team: "Product Management",
          explanation: [{ text: "John Reyes is a group product manager at Northwind Freight and writes its yearly product roadmap.", sources: [0] }],
          since: null, mention: null, confidence: "high", likely: false,
          said: { text: "He owns the roadmap.", speaker: "Priya Raman", time: "21:30" },
          evidence: [{ url: "https://northwindfreight.example/blog/roadmap-2026", label: "Northwind Freight product blog", date: "2026-01-08",
              quote: "John Reyes, Group Product Manager, walks through what our product teams are building in 2026." },
            { url: "https://conf.example.com/2026/speakers/john-reyes", label: "Example Conf speaker page", date: "", quote: "" }],
          found: { call: "Northwind Freight", title: "Discovery call: Northwind Freight and Spotify Portal", via: "your transcript", time: "21:30", at: "2026-10-21T15:30:00+00:00", how: "Found on the web" } },
      },
    ],
    orgs: [
      {
        id: "sample000004", kind: "company", name: "Brightwave Systems", domain: "", count: 1, source: "upload", status: "said", note: "", removed: false, connected: true,
        quote: { text: "Most of our alerts still go through Brightwave Systems.", speaker: "Marcus Bell", time: "24:02" },
        relation: { type: "vendor", label: "their vendor (logging)", detail: "logging", said: "They're our vendor for logging.", source: "said", sources: [],
          confidence: "", speaker: "Marcus Bell", time: "24:02" },
        explain: { kind: "company", name: "Brightwave Systems", type: "vendor", typeLabel: "Vendor or supplier", label: "their vendor (logging)", detail: "logging",
          explanation: [], since: null, evidence: [], mention: null, confidence: "",
          said: { text: "They're our vendor for logging.", speaker: "Marcus Bell", time: "24:02" },
          found: { call: "Northwind Freight", title: "Discovery call: Northwind Freight and Spotify Portal", via: "your transcript", time: "24:02", at: "2026-10-21T15:30:00+00:00", how: "Said on the call" } },
      },
      {
        id: "sample000005", kind: "company", name: "Harborline Labs", domain: "", count: 1, source: "upload", status: "found", note: "", removed: false, connected: true,
        quote: { text: "Harborline Labs keeps asking about the pilot too.", speaker: "Priya Raman", time: "27:15" },
        relation: { type: "partner", label: "partner", detail: "", said: "", source: "web", confidence: "medium", speaker: "", time: "",
          sources: [{ url: "https://harborline.example/partners", label: "Harborline Labs partners page" },
            { url: "https://news.example.com/2026/harborline-northwind", label: "Example News" }] },
        explain: { kind: "company", name: "Harborline Labs", type: "partner", typeLabel: "Partner", label: "partner", detail: "",
          explanation: [{ text: "Harborline Labs is a technology partner of Northwind Freight: its route-planning tools run on Northwind's shipment data.", sources: [0] },
            { text: "The two companies announced the partnership for Northwind's freight-tracking product in 2024.", sources: [1] }],
          since: { text: "2024", sources: [1] }, said: null, mention: null, confidence: "medium",
          evidence: [{ url: "https://harborline.example/partners", label: "Harborline Labs partners page", date: "2026-08",
              quote: "Northwind Freight: our route-planning tools run on Northwind's live shipment data." },
            { url: "https://news.example.com/2026/harborline-northwind", label: "Example News", date: "2024-06-18",
              quote: "Harborline Labs and Northwind Freight today announced a partnership around Northwind's freight-tracking product." }],
          found: { call: "Northwind Freight", title: "Discovery call: Northwind Freight and Spotify Portal", via: "your transcript", time: "27:15", at: "2026-10-21T15:30:00+00:00", how: "Found on the web" } },
      },
    ],
  },

  // The People map in the demo: what MOAB adds to the connections from the sample transcript above (all made up).
  mentioned: [
    { id: "m:sample000001", type: "person", label: "Grace Ito", sub: "Head of Finance", company: "Northwind Freight", callId: "northwind", mentioned: true },
    { id: "m:sample000002", type: "person", label: "Tom Hughes", sub: "Security Engineering Manager", company: "Northwind Freight", callId: "northwind", mentioned: true, auto: true },
    { id: "m:sample000003", type: "person", label: "John Reyes", sub: "Group Product Manager", company: "Northwind Freight", callId: "northwind", mentioned: true, auto: true },
    { id: "co:Brightwave Systems", type: "company", label: "Brightwave Systems", callId: "northwind", mentioned: true, relation: "vendor" },
    { id: "co:Harborline Labs", type: "company", label: "Harborline Labs", callId: "northwind", mentioned: true, relation: "partner" },
  ],

  // Spotify's own history with companies (stands in for HubSpot).
  companies: {
    "Northwind Freight": {
      engineers: 420, status: "Open deal: Portal", domain: "northwindfreight.example",
      history: [{ date: "2025-02", text: "Talked about the plugin bundle. Did not sign: no budget." }],
      // The company profile MOAB's research builds (server.py's records.orgs[domain].profile, contract v2). Made up, with made-up sources.
      profile: {
        v: 2, domain: "northwindfreight.example", name: "Northwind Freight", at: "2026-10-19T14:10:00+00:00", confidence: "high",
        summary: { text: "Northwind Freight moves freight by road and rail and sells live shipment tracking to its customers. Its platform team runs Backstage as the company's developer portal.", src: [0, 1] },
        facts: [
          { label: "Founded", value: "1998", src: [0] },
          { label: "Headquarters", value: "Rotterdam, Netherlands", src: [0] },
          { label: "Size", value: "About 420 engineers", src: [1] },
          { label: "Type", value: "Private company", src: [0] },
          { label: "Leaders", value: "Priya Raman, VP Platform Engineering", src: [2] },
          { label: "Products", value: "Freight tracking, warehouse software", src: [0] },
        ],
        what: [
          { text: "Runs road and rail freight across Europe and sells customers a live view of every shipment.", src: [0] },
          { text: "Builds its own warehouse software, used in every one of its warehouses.", src: [3] },
          { text: "Works with Harborline Labs, whose route planning runs on Northwind's shipment data.", src: [4] },
        ],
        news: [
          { when: "May 2026", text: "Hired Priya Raman as VP of Platform Engineering.", src: [2] },
          { when: "Mar 2026", text: "Finished a zero-trust security rollout across every warehouse.", src: [3] },
          { when: "Jun 2024", text: "Announced a partnership with Harborline Labs for freight tracking.", src: [4] },
        ],
        tech: [
          { text: "Runs Backstage itself; the platform blog names the developer experience team as its owner.", src: [1] },
          { text: "Their own blog says Backstage upgrades take the team weeks every quarter.", src: [1] },
          { text: "Security engineering ran the zero-trust rollout, so expect a security review before any pilot.", src: [3] },
        ],
        forCall: [
          { text: "Upgrades eat the platform team's time, in their own words: Portal takes that upkeep off them.", src: [1] },
          { text: "They just finished zero trust; lead with how Portal passes a security review.", src: [3] },
        ],
        sources: [
          { url: "https://northwindfreight.example/about", label: "Northwind Freight: about us" },
          { url: "https://northwindfreight.example/blog/backstage-upgrades", label: "Northwind Freight platform blog: keeping Backstage current" },
          { url: "https://northwindfreight.example/news/priya-raman-joins", label: "Northwind Freight news: Priya Raman joins" },
          { url: "https://northwindfreight.example/blog/zero-trust-rollout", label: "Northwind Freight engineering blog: zero trust in every warehouse" },
          { url: "https://news.example.com/2026/harborline-northwind", label: "Example News: Harborline Labs and Northwind Freight" },
        ],
      },
    },
    "Quillstack": {
      engineers: 80, status: "New lead", domain: "quillstack.example",
      history: [{ date: "2026-01", text: "Told them it was not a good fit yet: only 20 engineers." }],
      comeBack: { then: 20, now: 80, openJobs: 31 },
      profile: {
        v: 2, domain: "quillstack.example", name: "Quillstack", at: "2026-10-19T14:11:00+00:00", confidence: "high",
        summary: { text: "Quillstack makes contract drafting and review software for in-house legal teams. Founded in 2023, it has grown to about 80 engineers and is hiring 31 more.", src: [0, 1] },
        facts: [
          { label: "Founded", value: "2023", src: [0] },
          { label: "Headquarters", value: "Toronto, Canada (remote-first)", src: [0] },
          { label: "Size", value: "About 80 engineers, 31 open roles", src: [1] },
          { label: "Type", value: "Private, venture-backed (Series B)", src: [2] },
          { label: "Leaders", value: "Sam Okafor, CTO and co-founder", src: [0] },
          { label: "Product", value: "Quill, contract drafting and review", src: [3] },
        ],
        what: [
          { text: "Sells Quill, a tool legal teams use to draft contracts and review the other side's changes.", src: [3] },
          { text: "Engineering ships about 60 services, each with a named owning team.", src: [4] },
          { text: "Every engineer has used Claude Code and Codex since early 2026.", src: [4] },
        ],
        news: [
          { when: "Sep 2026", text: "Opened 31 engineering roles.", src: [1] },
          { when: "Jun 2025", text: "Raised a Series B to grow its engineering team.", src: [2] },
        ],
        tech: [
          { text: "Keeps service owners in CODEOWNERS files; the blog describes no developer portal or catalog.", src: [4] },
          { text: "Their coding agents look up owners from those files, so ownership data matters to them every day.", src: [4] },
        ],
        forCall: [
          { text: "Their agents need to know who owns what and why: that is Xirp's job, and it can feed Portal later.", src: [4] },
          { text: "Hiring 31 engineers makes onboarding speed a live problem right now.", src: [1] },
        ],
        sources: [
          { url: "https://quillstack.example/about", label: "Quillstack: about us" },
          { url: "https://quillstack.example/careers", label: "Quillstack careers" },
          { url: "https://news.example.com/2025/quillstack-series-b", label: "Example News: Quillstack raises a Series B" },
          { url: "https://quillstack.example/product", label: "Quillstack: the Quill product page" },
          { url: "https://quillstack.example/blog/agents-codebase-map", label: "Quillstack engineering blog: a map of the codebase for our agents" },
        ],
      },
    },
    "Rookery Retail": { engineers: 40, status: "New lead", history: [] },
    "Helix Health": { engineers: 900, status: "Customer since 2025: Portal and Confidence", history: [], customer: true },
    "Lumen Air": { engineers: 300, status: "Open deal: Portal", history: [{ date: "2026-08", text: "Pilot going well with Dana Li as the main supporter." }] },
  },

  // Signed papers (stands in for Google Drive and DocuSign).
  papers: {
    "Northwind Freight": { nda: { signed: true, date: "2025-02-11", where: "DocuSign" }, securityPack: { sent: "v3", sentOn: "2025-02-20" } },
    "Quillstack": { nda: { signed: false }, securityPack: null },
    "Rookery Retail": { nda: { signed: true, date: "2026-08-01", where: "DocuSign" }, securityPack: { sent: "v5", sentOn: "2026-08-03" } },
  },
  currentSecurityPack: "v5",

  // Relationships only Spotify's records would know. The map adds the ones it can work out itself
  // (who works where, who came from where, and who worked together before).
  relationships: [
    { a: "you", b: "p:dana.li@quillstack.example", kind: "warm", label: "your supporter",
      why: "Dana Li was your strongest supporter in the Lumen Air deal. She now runs developer productivity at Quillstack." },
    { a: "you", b: "p:marcus.bell@northwindfreight.example", kind: "warm", label: "Portal Office Hours",
      why: "Marcus Bell came to Portal Office Hours in March 2026, so he already knows you and the product." },
    { a: "you", b: "p:sam@quillstack.example", kind: "moved", label: "talked Jan 2026",
      why: "You spoke with Sam Okafor in January 2026 and told Quillstack it was not a good fit yet." },
    { a: "you", b: "co:Lumen Air", kind: "moved", label: "open deal",
      why: "Lumen Air is an open Portal deal. Dana Li leaving may weaken your support there." },
    { a: "you", b: "co:Helix Health", kind: "warm", label: "customer",
      why: "Helix Health has been a Spotify customer since 2025 (Portal and Confidence)." },
    // Mentioned on the Northwind call (the sample transcript): labelled with what was said, or what the web showed.
    { a: "p:priya.raman@northwindfreight.example", b: "m:sample000001", kind: "mentioned", label: "finance", src: "call", callId: "northwind",
      connId: "sc1", mentionId: "sample000001", source: "Sample data", why: "Grace Ito, Head of Finance. Priya Raman mentioned them on the call at 12:41." },
    { a: "p:marcus.bell@northwindfreight.example", b: "m:sample000002", kind: "mentioned", label: "security", src: "call", callId: "northwind",
      connId: "sc2", mentionId: "sample000002", source: "Sample data", why: "Tom Hughes, Security Engineering Manager. Marcus Bell mentioned them on the call at 18:05." },
    { a: "p:priya.raman@northwindfreight.example", b: "m:sample000003", kind: "mentioned", label: "owns the roadmap", src: "call", callId: "northwind",
      connId: "sc3", mentionId: "sample000003", source: "Sample data", why: "John Reyes, Group Product Manager. Priya Raman mentioned them on the call at 21:30. “He owns the roadmap.”" },
    { a: "p:marcus.bell@northwindfreight.example", b: "co:Brightwave Systems", kind: "mentioned", label: "their vendor (logging)", src: "call", callId: "northwind",
      connId: "sc4", mentionId: "sample000004", source: "Sample data", why: "Marcus Bell mentioned them on the call at 24:02. “They're our vendor for logging.”" },
    { a: "p:priya.raman@northwindfreight.example", b: "co:Harborline Labs", kind: "mentioned", label: "partner", src: "call", callId: "northwind",
      connId: "sc5", mentionId: "sample000005", source: "Sample data", why: "Priya Raman mentioned them on the call at 27:15. Relation found on the web.",
      sources: [{ url: "https://harborline.example/partners", label: "Harborline Labs partners page" }] },
  ],

  // Alerts the agent raised in the background between calls. callId links an alert to an upcoming call.
  watch: [
    { date: "Oct 2", kind: "Job change", callId: "quillstack", title: "Dana Li moved to Quillstack",
      text: "Dana Li, your strongest supporter at Lumen Air, moved to Quillstack. You may have less support at Lumen Air, and you now have a warm contact at Quillstack." },
    { date: "Oct 9", kind: "Come back", callId: "quillstack", title: "Quillstack grew to 80 engineers",
      text: "You told Quillstack 'not yet' in January when they had 20 engineers. They now have about 80 engineers and 31 open engineering jobs." },
  ],
};
