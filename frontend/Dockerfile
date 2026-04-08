FROM node:20-alpine AS build

WORKDIR /workspace

COPY package.json ./
RUN npm install --no-audit --no-fund

COPY angular.json tsconfig*.json ./
COPY src ./src

RUN npm run build -- --configuration production

FROM nginx:1.27-alpine AS runtime

COPY nginx/default.conf /etc/nginx/conf.d/default.conf
COPY --from=build /workspace/dist/zk-inventory /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
