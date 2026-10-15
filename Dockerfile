FROM golang:1.24-alpine AS build
WORKDIR /src
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/bumper-brawl .

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=build /out/bumper-brawl /app/bumper-brawl
COPY web/ /app/web/
ENV PORT=8080 WEB_DIR=/app/web
EXPOSE 8080
USER nonroot
ENTRYPOINT ["/app/bumper-brawl"]
