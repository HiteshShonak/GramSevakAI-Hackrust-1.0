# GramSevak AI Mobile App

Expo React Native app for GramSevak AI.

- Design language converted from the original Vite prototype
- Uses OTP auth against the FastAPI backend
- OTA-ready via Expo Updates / EAS configuration
- Supports English, Hindi, and cached backend-driven UI translations for other supported languages

## Local Setup

1. Copy `.env.example` to `.env`
2. Set `EXPO_PUBLIC_API_BASE_URL` to your backend URL
   Current local tunnel: `https://nestor-soppier-ike.ngrok-free.dev`
   This should point to your local backend running on `http://localhost:8080`
3. Set `EXPO_PUBLIC_EAS_PROJECT_ID` for OTA-enabled EAS builds
4. Run `npm install`
5. Run `npm run start`

## OTA

- `npm run ota:preview` publishes a preview update
- `npm run ota:production` publishes a production update
- Production builds use the `production` EAS channel

## Backend

The mobile app expects the GramSevak backend with:

- `ENABLE_PHASE2_API=true`
- `JWT_SECRET` configured
- MongoDB enabled for profile persistence
- For local device testing, start the backend on port `8080` and keep ngrok pointed to it
