FROM golang:1.24-alpine AS build
WORKDIR /src
COPY server/go.mod server/go.sum ./
RUN go mod download
COPY server/ ./
RUN CGO_ENABLED=0 go build -trimpath -ldflags="-s -w" -o /out/bumper-brawl .
# distroless has no shell to mkdir with, so the data dir is made here and copied over
RUN mkdir -p /out/data

FROM gcr.io/distroless/static-debian12:nonroot
WORKDIR /app
COPY --from=build /out/bumper-brawl /app/bumper-brawl
COPY web/ /app/web/
COPY --from=build --chown=nonroot:nonroot /out/data /data
ENV PORT=8080 WEB_DIR=/app/web DATA_DIR=/data
EXPOSE 8080
USER nonroot
ENTRYPOINT ["/app/bumper-brawl"]
