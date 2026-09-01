FROM node:26-slim

WORKDIR /app

COPY package.json package-lock.json* ./
RUN npm ci

COPY . .

EXPOSE 3000

# Vite dev server with hot module replacement (HMR).
# The --host 0.0.0.0 flag is required to make the dev server reachable
# from outside the container (i.e., from your browser on the host machine).
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]