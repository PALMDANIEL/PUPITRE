# Serveur de lecture en ligne Pupitre (AIT) : l'application mobile y envoie les photos de partitions.
# Construction : docker build -t pupitre-serveur .     Déploiement : voir deploy/LISEZ-MOI.md
FROM node:24-bookworm-slim AS web
WORKDIR /app
COPY package.json package-lock.json angular.json tsconfig.json tsconfig.app.json ./
RUN npm ci --no-audit --no-fund
COPY src ./src
COPY public ./public
RUN npx ng build

FROM ubuntu:24.04
ARG AUDIVERIS_VERSION=5.11.0
ENV DEBIAN_FRONTEND=noninteractive
# Audiveris (paquet Linux) veut ajouter une icône au menu du bureau : sans bureau sur un serveur, on lui prépare
# le dossier attendu, et s'il échoue malgré tout on ignore ce script d'icône (sans effet sur la lecture).
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl gnupg python3 python3-venv libglib2.0-0 fontconfig fonts-dejavu-core \
 && curl -fsSL https://deb.nodesource.com/setup_24.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && curl -fsSL -o /tmp/audiveris.deb "https://github.com/Audiveris/audiveris/releases/download/${AUDIVERIS_VERSION}/Audiveris-${AUDIVERIS_VERSION}-ubuntu24.04-x86_64.deb" \
 && mkdir -p /etc/xdg/menus/applications-merged /usr/share/applications /usr/share/desktop-directories \
 && { apt-get install -y --no-install-recommends /tmp/audiveris.deb \
      || { rm -f /var/lib/dpkg/info/audiveris.postinst && dpkg --configure -a; }; } \
 && test -x /opt/audiveris/bin/Audiveris \
 && rm -rf /tmp/audiveris.deb /var/lib/apt/lists/*

# Moteur Python (liste complète figée : --no-deps évite PyAudio, inutile)
COPY engine/requirements.txt /tmp/requirements.txt
RUN python3 -m venv /opt/venv && /opt/venv/bin/pip install --no-cache-dir --no-deps -r /tmp/requirements.txt

# Banque de sons GeneralUser GS (S. Christian Collins) et sa licence
RUN mkdir -p /opt/soundfont \
 && curl -fsSL -o /opt/soundfont/GeneralUser-GS.sf2 https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/GeneralUser-GS.sf2 \
 && curl -fsSL -o /opt/soundfont/LICENSE.txt https://raw.githubusercontent.com/mrbumpy409/GeneralUser-GS/main/documentation/LICENSE.txt

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --omit=dev --no-audit --no-fund
COPY server ./server
COPY licence ./licence
COPY engine ./engine
COPY --from=web /app/dist ./dist

ENV NODE_ENV=production NO_OPEN=1 PORT=3000 \
    ACCES_EN_LIGNE=1 STORE=files STORAGE_DIR=/data \
    PYTHON_BIN=/opt/venv/bin/python3 SOUNDFONT=/opt/soundfont/GeneralUser-GS.sf2 AUDIVERIS_BIN=/opt/audiveris/bin/Audiveris \
    JAVA_TOOL_OPTIONS=-Djava.awt.headless=true
VOLUME /data
EXPOSE 3000
HEALTHCHECK --interval=60s --timeout=5s CMD curl -fs http://localhost:3000/api/health || exit 1
CMD ["npx", "tsx", "server/main.ts"]
