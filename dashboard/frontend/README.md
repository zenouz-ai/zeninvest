# Investment Agent Dashboard - Frontend

React + TypeScript + Vite frontend for the Investment Agent dashboard.

## Setup

1. Install dependencies:
```bash
cd dashboard/frontend
npm install
```

2. Start development server:
```bash
npm run dev
```

The frontend will be available at `http://localhost:3000` and will proxy API requests to `http://localhost:8000` (the FastAPI backend).

## Build

To build for production:

```bash
npm run build
```

The built files will be in the `dist/` directory, ready to be served by FastAPI or nginx.

## Environment Variables

Create a `.env` file in `dashboard/frontend/`:

```
VITE_API_URL=http://localhost:8000
```

## Features

- **Dashboard Home**: Real-time activity feed via SSE, portfolio summary, latest run status
- **Stock Universe**: Searchable, filterable table of all stocks in the universe
- **Run History**: Timeline view of all analysis cycles with details
- **Portfolio**: Current positions, portfolio value history chart, sector allocation

## Tech Stack

- React 18
- TypeScript
- Vite
- Tailwind CSS
- React Router
- TanStack Table
- Recharts
- Axios

## Design

Dark theme with financial terminal aesthetic:
- Dark charcoal background (`#0a0a0a`)
- Electric green for gains (`#00ff88`)
- Warm red for losses (`#ff4444`)
- Cool blue for neutral/info (`#4a9eff`)
- Muted gold accents (`#ffd700`)
