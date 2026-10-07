# web

Next.js 16 (App Router, TypeScript strict, Tailwind v4, shadcn/ui Radix base) UI and BFF for the estimator. Commands: `pnpm lint | typecheck | test | check:types`, or `make web-check` from the repo root.

## Architecture notes
- **BFF:** `AI_SERVICE_URL` is server-only (`src/lib/ai-service/env.ts`, parsed lazily per call, never at module scope).
- **Typed client:** `src/lib/ai-service/schema.d.ts` is generated from `contracts/openapi.json` (`make web-types`); `make web-check` fails when it is stale.
- **Cache Components: off.** Everything flows through route handlers and client components, so there is nothing to cache, and the feature adds build-time failure modes (sync IO, uncached data outside `<Suspense>`).
- **Fonts:** the `geist` package, not `next/font/google`, so Docker and CI builds are hermetic.
- **Tokens:** documented at the top of `src/app/globals.css` (sober enterprise palette, one accent, light and dark).
