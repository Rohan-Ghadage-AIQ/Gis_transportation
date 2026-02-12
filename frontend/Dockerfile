# Stage 1: Build
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

# Stage 2: Serve with Nginx
FROM nginx:stable-alpine
# Copy build files from Stage 1 to Nginx
COPY --from=build /app/dist /usr/share/nginx/html
# Copy a custom nginx config if you have one, or use default
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]