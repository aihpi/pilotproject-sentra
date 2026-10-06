FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

FROM nginx:alpine

COPY --from=builder /app/dist /usr/share/nginx/html
# A template, not a finished conf: the entrypoint substitutes the local
# resolver into it before nginx starts. See nginx.conf.template.
COPY nginx.conf.template /etc/nginx/templates/default.conf.template

# Opt in to the entrypoint reading the nameservers out of /etc/resolv.conf
# into $NGINX_LOCAL_RESOLVERS. Off by default in the image; without it the
# template's `resolver` directive is substituted with nothing.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1

# The evaluation harness, as compose names it. Kubernetes overrides this
# with a fully qualified name, because nginx's resolver does not search.
ENV EVAL_HARNESS_HOST=eval-harness

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
