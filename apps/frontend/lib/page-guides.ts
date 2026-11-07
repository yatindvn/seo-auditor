/** The "how it works" copy for each public page (components/platform/page-guide.tsx). */

export const HOME_GUIDE = {
  title: "How an audit works",
  intro: "Enter a website address and choose how many pages to check. The crawler starts at that page, follows internal links and runs the same checks on every page it finds, then scores the site from 0 to 100. You can watch the crawl live while it runs.",
  points: [
    { term: "What is checked", text: "titles, descriptions, headings, canonical tags, broken links, redirects, page speed signals, security headers, structured data and accessibility." },
    { term: "Optional extras", text: "render JavaScript to compare what users and crawlers see, scan pages with axe for accessibility, and measure Core Web Vitals." },
    { term: "What you get", text: "a health score, issues ranked by impact with advice for each, and a project for the site that keeps every audit so you can track changes over time." },
  ],
};

export const KEYWORDS_GUIDE = {
  title: "How Keywords Explorer works",
  intro: "Type a seed keyword and choose a country. Ideas come from Google Autocomplete and the People Also Ask questions on the results page for your seed. Use it before you write, to find the questions people actually search for and how hard each one is to rank for.",
  points: [
    { term: "Metrics", text: "monthly search volume, cost per click, competition and keyword difficulty come from DataForSEO when it is connected; without it the page shows clearly marked preview data." },
    { term: "Traffic estimate", text: "a rough figure for the visits a top position could bring, worked out from search volume." },
    { term: "Clusters", text: "optionally groups keywords whose search results overlap, which usually means one page can rank for the whole group. This runs one search per keyword." },
    { term: "Export", text: "download every idea and its metrics as a CSV file." },
  ],
};

export const CONTENT_GUIDE = {
  title: "How Content Explorer works",
  intro: "Enter a topic and the tool fetches the top 10 Google results for it, then runs the same page analysis a site audit uses on each one. Use it before writing or rewriting a page, to see the length, structure and markup of the pages that already rank.",
  points: [
    { term: "Per result", text: "word count, H1 and heading outline, schema types, internal and external links, readability, issue count, referring domains and backlinks." },
    { term: "Summary", text: "the median length, the most used schema types and the words competitors repeat in their H2 headings: a quick picture of what a page needs to compete." },
    { term: "Cost and caching", text: "a new search uses one search request and two backlink requests, about five to eight cents. Repeating it within seven days is free; Refresh fetches it again." },
  ],
};

export const PROJECTS_GUIDE = {
  title: "What a project holds",
  intro: "Every site you audit gets a project, created automatically from its domain. Open one to see its history and the tools that work on that site. Schedules and alerts are set per project, so each site can be checked as often as it needs.",
  points: [
    { term: "Site Audit", text: "every audit of the site, with the change in health score and issues between any two of them." },
    { term: "Rank Tracker", text: "positions for the keywords you choose, checked on a schedule, compared with your competitors." },
    { term: "Content Gap and Backlinks", text: "keywords and linking sites your competitors have and you don't." },
    { term: "AI Visibility", text: "whether AI assistants mention and cite the site when people ask about your topic." },
    { term: "Search Console and Custom Rules", text: "Google's own clicks and indexing data, and checks you define for your site." },
  ],
};
