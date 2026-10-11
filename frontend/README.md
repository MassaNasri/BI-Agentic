# BI Voice Agent - Frontend

Modern React + Vite + TailwindCSS frontend for BI Voice Agent.

## Features

- ✅ React 18 + Vite
- ✅ TailwindCSS for styling
- ✅ React Router v6 for routing
- ✅ Zustand for state management
- ✅ Axios for API calls
- ✅ JWT authentication
- ✅ Protected routes
- ✅ Toast notifications
- ✅ Responsive design
- ✅ Dark mode ready

## Setup

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Create `.env` file:
```bash
cp .env.example .env
```

3. Start development server:
```bash
npm run dev
```

Server runs at: http://127.0.0.1:5173

## Build for Production

```bash
npm run build
npm run preview
```

## Project Structure

```
src/
├── api/              # API configuration
├── components/       # Shared components
├── layouts/          # Layout components
├── pages/            # Page components
├── store/            # Zustand stores
├── hooks/            # Custom hooks
├── utils/            # Utility functions
└── styles/           # Global styles
```

## Backend Integration

Ensure the Django backend is running at `http://127.0.0.1:8000`

The frontend is configured to work with CORS-enabled backend.

