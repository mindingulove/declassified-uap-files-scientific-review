
  (() => {
    const app = document.querySelector("#aaro");
    if (!app) return;

    if (app.dataset.aaroScriptInitialized === "true") return;
    app.dataset.aaroScriptInitialized = "true";

    const csvUrl = "/Portals/1/Interactive/2026/UFO/uap-csv.csv";

    const thumbs = Array.from(app.querySelectorAll(".thumb[data-lightbox-index]"));
    const dots = Array.from(app.querySelectorAll("[data-carousel-target]"));
    const carouselField = app.querySelector(".evidence-field");
    const carouselTrack = app.querySelector(".carousel-track");
    const prevButton = app.querySelector("[data-carousel-prev]");
    const nextButton = app.querySelector("[data-carousel-next]");
    const lightbox = document.getElementById("evidence-lightbox");
    const lightboxImage = document.getElementById("lightbox-image");
    const lightboxCaption = document.getElementById("lightbox-caption");
    const closeButton = document.querySelector("[data-lightbox-close]");
    const lightboxPrev = document.querySelector("[data-lightbox-prev]");
    const lightboxNext = document.querySelector("[data-lightbox-next]");

    const recordList = app.querySelector("#recordList, .record-list");
    const recordCount = app.querySelector("#recordCount");

    const recordModal = document.getElementById("record-modal");
    const recordModalShell = document.querySelector("[data-record-modal-shell]");
    const recordModalAgency = document.querySelector("[data-record-modal-agency]");
    const recordModalTitle = document.querySelector("[data-record-modal-title]");
    const recordModalCopy = document.querySelector("[data-record-modal-copy]");
    const recordModalFacts = document.querySelector("[data-record-modal-facts]");
    const recordModalMedia = document.querySelector("[data-record-modal-media]");
    const recordModalDownload = document.querySelector("[data-record-modal-download]");
    const recordModalClose = document.querySelector("[data-record-modal-close]");
    const recordPagination = app.querySelector("#recordPagination");
    let allRecords = [];
    let filteredRecords = [];
    let currentRecordPage = 1;
    const recordsPerPage = 10;
    let playedVideos = [];

    let currentSortField = "";
    let currentSortDirection = "asc";

    let activeIndex = 0;
    let lastFocus = null;
    let autoTimer = null;
    ///--> NEW CODE: deep-link flag - suppresses replaceState when close is triggered by popstate
    let _closingFromPopstate = false;
    ///--> END NEW CODE

    const autoDelay = 2600;
    const allowAuto = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    function parseCSV(csvText) {
      const rows = [];
      let row = [];
      let cell = "";
      let insideQuotes = false;

      for (let i = 0; i < csvText.length; i++) {
        const char = csvText[i];
        const nextChar = csvText[i + 1];

        if (char === '"' && insideQuotes && nextChar === '"') {
          cell += '"';
          i++;
        } else if (char === '"') {
          insideQuotes = !insideQuotes;
        } else if (char === "," && !insideQuotes) {
          row.push(cell.trim());
          cell = "";
        } else if ((char === "\n" || char === "\r") && !insideQuotes) {
          if (cell || row.length) {
            row.push(cell.trim());
            rows.push(row);
            row = [];
            cell = "";
          }

          if (char === "\r" && nextChar === "\n") i++;
        } else {
          cell += char;
        }
      }

      if (cell || row.length) {
        row.push(cell.trim());
        rows.push(row);
      }

      return rows;
    }

    function escapeHtml(value) {
      return String(value || "").replace(/[&<>"']/g, (char) => {
        return {
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[char];
      });
    }

    ///--> NEW CODE: titleToHash - converts a record title to a URL-safe hash fragment
    function titleToHash(title) {
      return String(title || "")
        .trim()
        .replace(/\s+/g, "-")
        .replace(/[^A-Za-z0-9\-_]/g, "")
        .replace(/-+/g, "-");
    }
    ///--> END NEW CODE

    function getFileType(url) {
      if (!url) return ".pdf";
      const cleanUrl = String(url).split("?")[0].trim();
      const match = cleanUrl.match(/\.[a-z0-9]+$/i);
      return match ? match[0].toLowerCase() : ".pdf";
    }

    function normalizeType(type) {
      if (!type) return ".pdf";
      const cleanType = String(type).trim().toLowerCase();
      return cleanType.startsWith(".") ? cleanType : "." + cleanType;
    }

    function getRecordKind(fileType) {
      return String(fileType || ".pdf")
        .replace(".", "")
        .toLowerCase();
    }

    function isVideo(fileType) {
      return [".mp4", ".webm", ".ogg", ".mov"].includes(fileType);
    }

    function isImage(fileType) {
      return [".jpg", ".jpeg", ".png", ".gif", ".webp", ".img"].includes(fileType);
    }

    ///--> NEW CODE: getDocumentType - normalize Document type field to 'video', 'image', or 'pdf'
    //              V* = video, I* = image, P* (or anything else) = pdf
    function getDocumentType(type) {
      if (!type) return "pdf";
      const first = String(type).trim()[0].toUpperCase();
      if (first === "V") return "video";
      if (first === "I") return "image";
      return "pdf";
    }
    ///--> END NEW CODE

    function renderRecordFacts(record) {
      return `
      <div class="record-modal-fact">
<dt>Asset File Name</dt>
<dd>[${escapeHtml(record.title)}]</dd>
      </div>

      <div class="record-modal-fact">
        <dt>Release Date</dt>
        <dd>[${escapeHtml(record.releaseDate)}]</dd>
      </div>

      <div class="record-modal-fact">
        <dt>Agency</dt>
        <dd>[${escapeHtml(record.agency)}]</dd>
      </div>

      <div class="record-modal-fact">
        <dt>Incident Date</dt>
        <dd>[${escapeHtml(record.incidentDate)}]</dd>
      </div>

      <div class="record-modal-fact">
        <dt>Incident Location</dt>
        <dd>[${escapeHtml(record.incidentLocation)}]</dd>
      </div>

      <div class="record-modal-fact">
        <dt>Document Type</dt>
        <dd>[${escapeHtml(record.fileType)}]</dd>
      </div>
    `;
    }

    function renderVideoMedia(record) {
      const videoIds = record.videoUrl
        ? record.videoUrl
            .split("|")
            .map(function (s) {
              return s.trim();
            })
            .filter(Boolean)
        : [];

      if (!videoIds.length) {
        return `
        <div class="record-video-preview" aria-label="Video footage preview">
          <span class="record-video-play">Video unavailable</span>
        </div>
      `;
      }

      const thumbsHtml =
        videoIds.length > 1
          ? '<div class="record-thumbs" aria-label="Video thumbnails"></div>'
          : "";

      const firstImageUrl = record.imageUrl ? record.imageUrl.split("|")[0].trim() : "";
      const posterAttr = firstImageUrl ? ` poster="${escapeHtml(firstImageUrl)}"` : "";

      return `
      <div class="record-video-preview" aria-label="Video footage preview">
        <span class="record-corner record-corner-top-left" aria-hidden="true"></span>
        <span class="record-corner record-corner-top-right" aria-hidden="true"></span>
        <span class="record-corner record-corner-bottom-left" aria-hidden="true"></span>
        <span class="record-corner record-corner-bottom-right" aria-hidden="true"></span>
        <span class="record-video-play">Play footage</span>
        <video controls="" crossorigin="anonymous" id="record-video-player" playsinline=""${posterAttr}
               style="position:absolute;inset:0;width:100%;height:100%;object-fit:contain;z-index:1;">&nbsp;</video>
      </div>
      ${thumbsHtml}
    `;
    }

    function renderImageMedia(record) {
      const imageUrls = record.imageUrl
        ? record.imageUrl
            .split("|")
            .map(function (s) {
              return s.trim();
            })
            .filter(Boolean)
        : [];

      if (!imageUrls.length) {
        return `
        <div class="record-image-preview" aria-label="Image preview">
          <span class="record-image-label">Image unavailable</span>
        </div>
      `;
      }

      const thumbsHtml =
        imageUrls.length > 1
          ? '<div class="record-thumbs" aria-label="Image thumbnails"></div>'
          : "";

      return `
      <div class="record-image-preview" aria-label="Image preview">
        <img id="record-main-image"
             src="${escapeHtml(imageUrls[0])}"
             alt="${escapeHtml(record.title)}"
             style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;z-index:1;">
      </div>
      ${thumbsHtml}
    `;
    }

    function renderPdfMedia(record) {
      if (record.imageUrl) {
        return renderImageMedia(record);
      }

      return `
      <div class="record-pdf-preview" aria-label="PDF preview">
        <div class="record-pdf-clearance">CLEARED<br>For Open Publication<br>${escapeHtml(record.releaseDate)}</div>
        <div class="record-pdf-seal">${escapeHtml(record.agency.charAt(0) || "R")}</div>
        <p class="record-pdf-agency">${escapeHtml(record.agency)}</p>
        <p class="record-pdf-title">${escapeHtml(record.title)}</p>
        <p class="record-pdf-page">1</p>
      </div>
    `;
    }

    function renderRecordMedia(record) {
      const docType = getDocumentType(record.documentType);
      if (docType === "video") return renderVideoMedia(record);
      if (docType === "image") return renderImageMedia(record);
      return renderPdfMedia(record);
    }

    function hydrateRecordModal(record) {
      if (
        !recordModal ||
        !recordModalShell ||
        !recordModalTitle ||
        !recordModalCopy ||
        !recordModalFacts ||
        !recordModalMedia ||
        !recordModalDownload
      ) {
        return;
      }

      recordModal.dataset.recordKind = record.kind;
      recordModalShell.dataset.recordKind = record.kind;

      if (recordModalAgency) {
        recordModalAgency.textContent = `[${record.agency || "AARO"}]`;
      }

      recordModalTitle.textContent =
        record.title || record.assetFileName || "Record detail";

      const descriptionHtml = record.description
        ? record.description.replace(/[\r\n]+/g, "<br/><br/>")
        : "";

      const redactedSentence =
        record.redacted && record.redacted.trim()
          ? `<p class="record-modal-redacted">Redactions have been made to protect the identity of eyewitnesses, the location of government facilities, or potentially sensitive information about military sites not related to UAP. No redactions have been made to any files released under President Trump's directive concerning information about the nature or existence of any encounter reported as a UAP or related phenomena.</p>`
          : "";

      recordModalCopy.innerHTML = `
  <p>${descriptionHtml}</p>
  ${redactedSentence}
`;

      recordModalFacts.innerHTML = renderRecordFacts(record);
      recordModalMedia.innerHTML = renderRecordMedia(record);

      recordModalMedia.insertAdjacentHTML(
        "beforeend",
        '<div class="record-related-media" data-record-related-media="" hidden></div>'
      );

      const _docType = getDocumentType(record.documentType);

      const _videoIds = record.videoUrl
        ? record.videoUrl
            .split("|")
            .map(function (s) {
              return s.trim();
            })
            .filter(Boolean)
        : [];

      const _imageUrls = record.imageUrl
        ? record.imageUrl
            .split("|")
            .map(function (s) {
              return s.trim();
            })
            .filter(Boolean)
        : [];

      if (_docType === "video") {
        recordModalDownload.disabled = true;
        recordModalDownload.textContent = "Download Video";
        recordModalDownload.setAttribute("aria-label", "Preparing download...");
        recordModalDownload.onclick = null;

        if (typeof initVideoPlayer === "function") {
          initVideoPlayer(_videoIds);
        }
      } else if (_docType === "image") {
        const _dlUrl = record.documentUrl || _imageUrls[0] || null;

        recordModalDownload.disabled = !_dlUrl;
        recordModalDownload.textContent = "Download Image";
        recordModalDownload.setAttribute(
          "aria-label",
          _dlUrl ? `Download ${record.title}` : "Download unavailable"
        );

        recordModalDownload.onclick = _dlUrl
          ? function () {
              window.open(_dlUrl, "_blank", "noopener");
            }
          : null;

        if (_imageUrls.length > 1 && typeof buildImageThumbs === "function") {
          buildImageThumbs(_imageUrls);
        }
      } else {
        const _dlUrl = record.documentUrl || null;

        recordModalDownload.disabled = !_dlUrl;
        recordModalDownload.textContent = "Download";
        recordModalDownload.setAttribute(
          "aria-label",
          _dlUrl ? `Download ${record.title}` : "Download unavailable"
        );

        recordModalDownload.onclick = _dlUrl
          ? function () {
              window.open(_dlUrl, "_blank", "noopener");
            }
          : null;
      }

      buildRelatedMedia(record);
    }

    function openRecordModal(record) {
      if (!recordModal || !recordModalClose) return;

      stopAuto();
      hydrateRecordModal(record);

      lastFocus = document.activeElement;
      recordModal.hidden = false;

      document.body.classList.add("lightbox-open");

      recordModalClose.focus();

      history.pushState(null, "", "#" + titleToHash(record.title));
    }

    function closeRecordModal() {
      if (!recordModal || recordModal.hidden) return;

      const video = recordModal.querySelector("video");

      if (video) video.pause();

      recordModal.hidden = true;

      document.body.classList.remove("lightbox-open");

      restartAuto();

      if (!_closingFromPopstate) {
        history.replaceState(null, "", location.pathname + location.search);
      }

      if (lastFocus && typeof lastFocus.focus === "function") {
        lastFocus.focus();
      }
    }

    function renderRecordRows(records, page = 1) {
      if (!recordList) return;

      currentRecordPage = page;
      recordList.innerHTML = "";

      const start = (currentRecordPage - 1) * recordsPerPage;
      const end = start + recordsPerPage;
      const pagedRecords = records.slice(start, end);

      pagedRecords.forEach((record, index) => {
        const row = document.createElement("button");

        row.className = "record-row";
        row.type = "button";
        row.dataset.recordTrigger = "";
        row.dataset.recordId = `record-${String(start + index + 1).padStart(3, "0")}`;

        row.innerHTML = `
      <span class="record-title">${escapeHtml(record.title)}</span>
      <span class="record-meta">[${escapeHtml(record.agency)}]</span>
      <span class="record-meta">[${escapeHtml(record.releaseDate)}]</span>
      <span class="record-meta">[${escapeHtml(record.incidentDate)}]</span>
      <span class="record-meta">[${escapeHtml(record.incidentLocation)}]</span>
      <span class="record-meta">[${escapeHtml(record.fileType)}]</span>
      <span class="row-arrow" aria-hidden="true"></span>
    `;

        row.addEventListener("click", () => {
          openRecordModal(record);
        });

        recordList.appendChild(row);
      });

      renderRecordPagination(records);
    }

    function getPaginationRange(currentPage, totalPages) {
      const isMobile = window.matchMedia("(max-width: 767px)").matches;
      const isTablet = window.matchMedia("(max-width: 1024px)").matches;

      const siblingCount = isMobile ? 0 : isTablet ? 1 : 2;
      const pages = [];

      const startPage = Math.max(2, currentPage - siblingCount);
      const endPage = Math.min(totalPages - 1, currentPage + siblingCount);

      pages.push(1);

      if (startPage > 2) pages.push("...");

      for (let i = startPage; i <= endPage; i++) {
        pages.push(i);
      }

      if (endPage < totalPages - 1) pages.push("...");

      if (totalPages > 1) pages.push(totalPages);

      return pages;
    }

    function renderRecordPagination(records) {
      if (!recordPagination) return;

      const totalPages = Math.ceil(records.length / recordsPerPage);
      recordPagination.innerHTML = "";

      if (totalPages <= 1) return;

      const prevButton = document.createElement("button");
      prevButton.type = "button";
      prevButton.className = "pagination-button pagination-prev";
      prevButton.textContent = "Prev";
      prevButton.disabled = currentRecordPage === 1;

      prevButton.addEventListener("click", () => {
        if (currentRecordPage > 1) {
          renderRecordRows(records, currentRecordPage - 1);
        }
      });

      recordPagination.appendChild(prevButton);

      getPaginationRange(currentRecordPage, totalPages).forEach((page) => {
        if (page === "...") {
          const dots = document.createElement("span");
          dots.className = "pagination-ellipsis";
          dots.textContent = "...";
          recordPagination.appendChild(dots);
          return;
        }

        const pageButton = document.createElement("button");
        pageButton.type = "button";
        pageButton.className = "pagination-button";
        pageButton.textContent = page;

        if (page === currentRecordPage) {
          pageButton.classList.add("is-active");
          pageButton.setAttribute("aria-current", "page");
        }

        pageButton.addEventListener("click", () => {
          renderRecordRows(records, page);
        });

        recordPagination.appendChild(pageButton);
      });

      const nextButton = document.createElement("button");
      nextButton.type = "button";
      nextButton.className = "pagination-button pagination-next";
      nextButton.textContent = "Next";
      nextButton.disabled = currentRecordPage === totalPages;

      nextButton.addEventListener("click", () => {
        if (currentRecordPage < totalPages) {
          renderRecordRows(records, currentRecordPage + 1);
        }
      });

      recordPagination.appendChild(nextButton);
    }

    function loadRecordsFromCSV() {
      if (!recordList) return;

      fetch(csvUrl)
        .then((response) => response.text())
        .then((csv) => {
          const rows = parseCSV(csv);
          const cleanHeader = (value) =>
            String(value || "")
              .replace(/^\uFEFF/, "")
              .trim()
              .toLowerCase();

          const headers = rows[0].map(cleanHeader);

          const get = (cols, name) => {
            const index = headers.indexOf(cleanHeader(name));
            return index >= 0 ? cols[index] || "" : "";
          };

          allRecords = rows.slice(1).map((cols) => {
            const redacted = get(cols, "Redaction");
            const releaseDate = get(cols, "Release Date");
            const title = get(cols, "Title");
            const documentType = get(cols, "Type");
            const videoPairing = get(cols, "Video pairing");
            const pdfPairing = get(cols, "PDF PAiring");
            const description = get(cols, "Description Blurb");
            const videoUrl = get(cols, "DVIDS Video ID");
            const agency = get(cols, "Agency");
            const incidentDate = get(cols, "Incident Date");
            const incidentLocation = get(cols, "Incident Location") || "N/A";
            const documentUrl = get(cols, "PDF | Image Link");
            const imageUrl = get(cols, "Modal Image");

            const fileType = documentType
              ? normalizeType(documentType)
              : getFileType(documentUrl || imageUrl || videoUrl);

            const kind = getRecordKind(fileType);

            return {
              redacted,
              releaseDate,
              title,
              documentType,
              videoPairing,
              pdfPairing,
              description,
              videoUrl,
              agency,
              incidentDate,
              incidentLocation,
              documentUrl,
              imageUrl,
              fileType,
              kind,
            };
          });

          if (recordCount) {
            recordCount.textContent = allRecords.length;
          }

          filteredRecords = allRecords;
          renderRecordRows(filteredRecords, 1);

          const initialHash = location.hash.slice(1);
          if (initialHash) {
            const matched = allRecords.find(function (r) {
              return titleToHash(r.title) === initialHash;
            });
            if (matched && recordModal && recordModalClose) {
              stopAuto();
              hydrateRecordModal(matched);
              lastFocus = null;
              recordModal.hidden = false;
              document.body.classList.add("lightbox-open");
              recordModalClose.focus();
            }
          }
        })
        .catch((error) => {
          console.error("CSV could not be loaded:", error);
        });
    }

    const wrapIndex = (index) => {
      return (index + thumbs.length) % thumbs.length;
    };

    const getCaption = (index) => {
      const thumb = thumbs[index];

      const image = thumb?.querySelector("img");

      const title = thumb?.dataset.lightboxTitle || image?.alt || "Evidence photo";

      const sentence = thumb?.dataset.lightboxSentence || "";

      return {title, sentence};
    };

    const carouselSlot = (index, activeIdx) => {
      const len = thumbs.length;
      let d = index - activeIdx;

      if (d > len / 2) d -= len;
      if (d < -len / 2) d += len;

      return d;
    };

    const layoutCarouselOrder = () => {
      thumbs.forEach((thumb, index) => {
        const slot = carouselSlot(index, activeIndex);
        thumb.style.order = String(slot + thumbs.length);
      });
    };

    const syncTrackPaddingAndScroll = (behavior) => {
      if (!carouselField || !carouselTrack || !thumbs.length) return;

      const fieldRect = carouselField.getBoundingClientRect();

      if (fieldRect.bottom <= 0 || fieldRect.top >= window.innerHeight) return;

      const el = thumbs[activeIndex];
      const cw = carouselField.clientWidth;
      const ew = el.getBoundingClientRect().width;
      const pad = Math.max(0, (cw - ew) / 2);

      carouselTrack.style.paddingLeft = `${pad}px`;
      carouselTrack.style.paddingRight = `${pad}px`;

      void carouselField.offsetHeight;

      const elRect = el.getBoundingClientRect();
      const fieldRect2 = carouselField.getBoundingClientRect();
      const elCenter = elRect.left + elRect.width / 2;
      const fieldCenter = fieldRect2.left + fieldRect2.width / 2;
      const delta = elCenter - fieldCenter;
      const maxScroll = Math.max(
        0,
        carouselField.scrollWidth - carouselField.clientWidth
      );
      const next = carouselField.scrollLeft + delta;
      const left = Math.min(Math.max(0, next), maxScroll);

      carouselField.scrollTo({
        left,
        behavior: behavior === "smooth" ? "smooth" : "auto",
      });
    };

    const syncActiveCenter = () => {
      requestAnimationFrame(() => {
        syncTrackPaddingAndScroll("auto");
      });
    };

    const setActive = (index) => {
      if (!thumbs.length) return;

      activeIndex = wrapIndex(index);

      thumbs.forEach((thumb, thumbIndex) => {
        const isActive = thumbIndex === activeIndex;
        thumb.classList.toggle("is-active", isActive);
        thumb.setAttribute("aria-pressed", isActive ? "true" : "false");
      });

      dots.forEach((dot, dotIndex) => {
        const isActive = dotIndex === activeIndex;
        dot.classList.toggle("is-active", isActive);
        dot.setAttribute("aria-current", isActive ? "true" : "false");
      });

      layoutCarouselOrder();
      syncActiveCenter();
    };

    const hydrateLightbox = () => {
      if (!thumbs.length || !lightboxImage || !lightboxCaption) return;

      const image = thumbs[activeIndex].querySelector("img");
      if (!image) return;

      lightboxImage.src = image.src;
      lightboxImage.alt = image.alt;
      const caption = getCaption(activeIndex);

      lightboxCaption.innerHTML = `<strong>${escapeHtml(caption.title)}</strong>
      ${caption.sentence ? `<span>${escapeHtml(caption.sentence)}</span>` : ""}`;
    };

    const openLightbox = (index) => {
      if (!lightbox) return;

      stopAuto();
      setActive(index);
      hydrateLightbox();
      lastFocus = document.activeElement;
      lightbox.hidden = false;
      document.body.classList.add("lightbox-open");
      closeButton?.focus();
    };

    const closeLightbox = () => {
      if (!lightbox) return;

      lightbox.hidden = true;
      document.body.classList.remove("lightbox-open");
      restartAuto();

      if (lastFocus && typeof lastFocus.focus === "function") {
        lastFocus.focus();
      }
    };

    const advance = (direction) => {
      setActive(activeIndex + direction);

      if (lightbox && !lightbox.hidden) {
        hydrateLightbox();
      }
    };

    function stopAuto() {
      if (autoTimer) {
        window.clearInterval(autoTimer);
        autoTimer = null;
      }
    }

    function startAuto() {
      if (!allowAuto || autoTimer || (recordModal && !recordModal.hidden)) return;

      autoTimer = window.setInterval(() => {
        if (
          document.hidden ||
          (lightbox && !lightbox.hidden) ||
          (recordModal && !recordModal.hidden)
        )
          return;

        advance(1);
      }, autoDelay);
    }

    function restartAuto() {
      stopAuto();
      startAuto();
    }

    thumbs.forEach((thumb, index) => {
      thumb.addEventListener("click", () => {
        openLightbox(index);
      });
    });

    dots.forEach((dot, index) => {
      dot.addEventListener("click", () => {
        setActive(index);
        restartAuto();
      });
    });

    prevButton?.addEventListener("click", () => {
      advance(-1);
      restartAuto();
    });

    nextButton?.addEventListener("click", () => {
      advance(1);
      restartAuto();
    });

    closeButton?.addEventListener("click", closeLightbox);
    recordModalClose?.addEventListener("click", closeRecordModal);

    lightboxPrev?.addEventListener("click", () => {
      advance(-1);
    });

    lightboxNext?.addEventListener("click", () => {
      advance(1);
    });

    lightbox?.addEventListener("click", (event) => {
      if (event.target === lightbox) closeLightbox();
    });

    recordModal?.addEventListener("click", (event) => {
      if (event.target === recordModal) closeRecordModal();
    });

    document.addEventListener("keydown", (event) => {
      const isLightboxOpen = lightbox ? !lightbox.hidden : false;
      const isRecordModalOpen = recordModal ? !recordModal.hidden : false;

      if (!isLightboxOpen && !isRecordModalOpen) return;

      if (event.key === "Escape") {
        if (isRecordModalOpen) {
          closeRecordModal();
        } else {
          closeLightbox();
        }

        return;
      }

      if (!isLightboxOpen) return;

      if (event.key === "ArrowLeft") advance(-1);
      if (event.key === "ArrowRight") advance(1);
    });

    carouselField?.addEventListener("mouseenter", stopAuto);
    carouselField?.addEventListener("mouseleave", startAuto);
    carouselField?.addEventListener("focusin", stopAuto);
    carouselField?.addEventListener("focusout", startAuto);

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) {
        stopAuto();
      } else {
        startAuto();
      }
    });

    window.addEventListener("resize", () => {
      syncTrackPaddingAndScroll("auto");
    });

    window.addEventListener("popstate", function () {
      const hash = location.hash.slice(1);
      if (hash) {
        const matched = allRecords.find(function (r) {
          return titleToHash(r.title) === hash;
        });
        if (matched && recordModal && recordModalClose) {
          stopAuto();
          hydrateRecordModal(matched);
          lastFocus = document.activeElement;
          recordModal.hidden = false;
          document.body.classList.add("lightbox-open");
          recordModalClose.focus();
        }
      } else {
        _closingFromPopstate = true;
        closeRecordModal();
        _closingFromPopstate = false;
      }
    });

    if (
      thumbs.length &&
      lightbox &&
      lightboxImage &&
      lightboxCaption &&
      carouselField &&
      carouselTrack
    ) {
      setActive(0);
      startAuto();
    }

    loadRecordsFromCSV();

    app.querySelectorAll("[data-sort-field]").forEach((button) => {
      button.addEventListener("click", () => {
        const field = button.dataset.sortField;

        app.querySelectorAll("[data-sort-field]").forEach((btn) => {
          btn.classList.remove("is-active-sort", "is-sort-asc", "is-sort-desc");
        });

        button.classList.add("is-active-sort");
        button.classList.add(
          currentSortField === field && currentSortDirection === "asc"
            ? "is-sort-desc"
            : "is-sort-asc"
        );

        sortRecords(filteredRecords, field);
      });
    });

    ///--> NEW CODE: DYNAMIC VIDEO LOADING
    const VIDEO_ID = 1005876;
    const DVIDS_API_KEY = "key-68bb60d16b35e";

    function escapeVideoHtml(v) {
      return String(v).replace(/[&<>"']/g, function (c) {
        return {
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        }[c];
      });
    }

    function formatDuration(secs) {
      if (secs == null || isNaN(Number(secs))) return "-";
      secs = Math.floor(Number(secs));
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = secs % 60;
      return (
        String(h).padStart(2, "0") +
        ":" +
        String(m).padStart(2, "0") +
        ":" +
        String(s).padStart(2, "0")
      );
    }

    function formatDate(iso) {
      if (!iso) return "-";
      const d = new Date(iso);
      if (isNaN(d.getTime())) return "-";
      return d.toISOString().slice(0, 10);
    }

    async function loadVideo(videoId, autoplay) {
      const videoElement = document.getElementById("record-video-player");
      if (!videoElement) return;

      ANALYTICSLIBRARY.init([videoId, "66"]);
      ANALYTICSLIBRARY.loadAnalyticsParam();

      const apiEndpoint = `https://api.dvidshub.net/asset?api_key=${DVIDS_API_KEY}&id=video:${videoId}&thumb_width=720`;

      try {
        const response = await fetch(apiEndpoint, {method: "GET"});

        if (!response.ok) {
          console.log(response.status);
          return;
        }

        const json = await response.json();
        const d = json.results || json.data || json;

        videoElement.innerHTML = "";
        videoElement.crossOrigin = "anonymous";
        if (autoplay) videoElement.removeAttribute("poster");

        if (d.hls_url) {
          if (Hls.isSupported()) {
            var hls = new Hls();
            hls.loadSource(d.hls_url);
            hls.attachMedia(videoElement);
          } else if (videoElement.canPlayType("application/vnd.apple.mpegurl")) {
            videoElement.src = d.hls_url;
          }
        }

        if (d.closed_caption_urls && d.closed_caption_urls.webvtt) {
          const track = document.createElement("track");
          track.kind = "subtitles";
          track.label = "English";
          track.srclang = "en";
          track.src = d.closed_caption_urls.webvtt;
          track.default = true;
          videoElement.appendChild(track);
        }

        videoElement.load();
        if (autoplay) videoElement.play();

        if (!autoplay) {
          const downloadBtn = document.querySelector("[data-record-modal-download]");
          if (downloadBtn && d.files) {
            const highestMp4 = d.files
              .filter(function (f) {
                return f.type === "video/mp4";
              })
              .sort(function (a, b) {
                return b.height - a.height;
              })[0];
            if (highestMp4) {
              downloadBtn.removeAttribute("disabled");
              downloadBtn.onclick = null;
              downloadBtn.onclick = async function () {
                try {
                  // Fetching as a blob "tricks" the browser into thinking the file is local
                  const response = await fetch(highestMp4.src);
                  const blob = await response.blob();
                  const url = window.URL.createObjectURL(blob);

                  const filename = highestMp4.src.split("/").pop();

                  const a = document.createElement("a");
                  a.style.display = "none";
                  a.href = url;
                  a.download = filename; // This will now be honored
                  document.body.appendChild(a);
                  a.click();

                  // --- GA4 TRACKING START ---
                  if (typeof gtag === "function") {
                    gtag("event", "file_download", {
                      file_extension: "mp4",
                      file_name: d.title,
                      link_url: highestMp4.src,
                    });
                  }
                  // --- GA4 TRACKING END ---

                  // Cleanup memory
                  window.URL.revokeObjectURL(url);
                  document.body.removeChild(a);
                } catch (e) {
                  console.log(e);
                  // Backup: If something goes wrong, open in new tab
                  window.open(highestMp4.src, "_blank");
                }
              };
            }
          }

          const factsEl = document.querySelector("[data-record-modal-facts]");
          if (factsEl) {
            const facts = [
              ["Date Taken", formatDate(d.date)],
              ["Date Posted", formatDate(d.date_published)],
              ["Category", d.category || "-"],
              ["Length", formatDuration(d.duration)],
              ["Location", (d.location && d.location.country_abbreviation) || "-"],
            ];
            factsEl.innerHTML = facts
              .map(function (pair) {
                return (
                  '<div class="record-modal-fact"><dt>' +
                  escapeVideoHtml(pair[0]) +
                  "</dt><dd>[" +
                  escapeVideoHtml(pair[1]) +
                  "]</dd></div>"
                );
              })
              .join("");
          }
        }
      } catch (error) {
        console.error("Failed to load video " + videoId + ":", error);
      }
    }

    function attachVideoControls() {
      const preview = document.querySelector(".record-video-preview");
      const video = document.getElementById("record-video-player");
      if (!preview || !video) return;

      video.addEventListener("play", function () {
        preview.classList.add("is-playing");
        preview.classList.remove("is-paused");
      });

      video.addEventListener("playing", function (e) {
        if (!playedVideos.includes(analyticsParams.type_id)) {
          playedVideos.push(analyticsParams.type_id);
          DVIDSVideoAnalytics.track("play", analyticsParams);
        }
      });

      video.addEventListener("pause", function () {
        preview.classList.remove("is-playing");
        preview.classList.add("is-paused");
      });

      video.addEventListener("ended", function () {
        preview.classList.remove("is-playing");
        preview.classList.add("is-paused");
        DVIDSVideoAnalytics.track("ended", analyticsParams);
      });

      preview.addEventListener("click", function (e) {
        if (e.target.closest("video")) return;
        if (video.paused) {
          video.play();
        } else {
          video.pause();
        }
      });
    }

    function initVideoPlayer(videoIds) {
      if (!videoIds || !videoIds.length) return;
      loadVideo(videoIds[0]);
      attachVideoControls(videoIds[0]);
      if (videoIds.length > 1 && typeof buildVideoThumbs === "function")
        buildVideoThumbs(videoIds);
    }

    function sortRecords(records, field) {
      const recordsToSort = records || allRecords;

      if (currentSortField === field) {
        currentSortDirection = currentSortDirection === "asc" ? "desc" : "asc";
      } else {
        currentSortField = field;
        currentSortDirection = "asc";
      }

      recordsToSort.sort((a, b) => {
        let aValue = a[field] || "";
        let bValue = b[field] || "";

        if (field === "releaseDate" || field === "incidentDate") {
          aValue = new Date(aValue);
          bValue = new Date(bValue);

          if (isNaN(aValue)) aValue = new Date(0);
          if (isNaN(bValue)) bValue = new Date(0);
        } else {
          aValue = String(aValue).toLowerCase();
          bValue = String(bValue).toLowerCase();
        }

        if (aValue < bValue) return currentSortDirection === "asc" ? -1 : 1;
        if (aValue > bValue) return currentSortDirection === "asc" ? 1 : -1;

        return 0;
      });

      renderRecordRows(recordsToSort, 1);
    }

    function setActiveThumb(identifier) {
      document.querySelectorAll(".record-thumb[data-thumb-id]").forEach(function (el) {
        el.classList.toggle("is-active", el.dataset.thumbId === String(identifier));
      });
    }

    async function fetchVideoMeta(videoId) {
      const url = `https://api.dvidshub.net/asset?api_key=${DVIDS_API_KEY}&id=video:${videoId}&thumb_width=400`;
      const response = await fetch(url);
      if (!response.ok) return null;
      const json = await response.json();
      return json.results || json.data || json;
    }

    async function buildVideoThumbs(videoIds) {
      const container = document.querySelector(".record-thumbs");
      if (!container) return;

      container.innerHTML = "";
      const metas = await Promise.all(videoIds.map(fetchVideoMeta));

      metas.forEach(function (data, i) {
        if (!data) return;
        const thumbUrl = data.thumbnail && data.thumbnail.url ? data.thumbnail.url : "";
        const videoId = videoIds[i];

        const item = document.createElement("span");
        item.className = "record-thumb";
        item.dataset.thumbId = String(videoId);

        if (thumbUrl) {
          const img = document.createElement("img");
          img.src = thumbUrl;
          img.alt = "";
          img.style.cssText =
            "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;";
          item.appendChild(img);
        }

        item.addEventListener("click", function () {
          setActiveThumb(videoId);
          loadVideo(videoId, true);
        });

        container.appendChild(item);
      });

      setActiveThumb(videoIds[0]);
    }

    function buildImageThumbs(imageUrls) {
      const container = document.querySelector(".record-thumbs");
      if (!container) return;

      container.innerHTML = "";

      imageUrls.forEach(function (url, i) {
        const item = document.createElement("span");
        item.className = "record-thumb";
        item.dataset.thumbId = String(i);

        const img = document.createElement("img");
        img.src = url;
        img.alt = "";
        img.style.cssText =
          "position:absolute;inset:0;width:100%;height:100%;object-fit:cover;";
        item.appendChild(img);

        item.addEventListener("click", function () {
          setActiveThumb(i);
          const mainImg = document.getElementById("record-main-image");
          if (mainImg) mainImg.src = url;
        });

        container.appendChild(item);
      });

      setActiveThumb(0);
    }

    async function buildRelatedMedia(record) {
      var container = document.querySelector("[data-record-related-media]");
      if (!container) return;

      container.hidden = true;
      container.innerHTML = "";

      var docType = getDocumentType(record.documentType);
      var linkItems = [];

      function addImageLinks() {
        var urls = record.imageUrl
          ? record.imageUrl
              .split("|")
              .map(function (s) {
                return s.trim();
              })
              .filter(Boolean)
          : [];
        urls.forEach(function (url) {
          linkItems.push({url: url, label: url.split("/").pop() || url});
        });
      }

      function addDocumentLink() {
        if (!record.documentUrl) return;

        var fileName = record.documentUrl.split("/").pop() || record.documentUrl;

        // For video records prepend mission-report-
        if (docType === "video") {
          fileName = "mission-report-" + fileName;
        }

        linkItems.push({
          url: record.documentUrl,
          label: fileName,
        });
      }

      async function addVideoLinks() {
        var videoIds = record.videoUrl
          ? record.videoUrl
              .split("|")
              .map(function (s) {
                return s.trim();
              })
              .filter(Boolean)
          : [];
        if (!videoIds.length) return;
        var metas = await Promise.all(videoIds.map(fetchVideoMeta));
        metas.forEach(function (data) {
          if (!data || !data.files) return;
          var bestMp4 = data.files
            .filter(function (f) {
              return f.type === "video/mp4";
            })
            .sort(function (a, b) {
              return b.height - a.height;
            })[0];
          if (bestMp4 && bestMp4.src) {
            linkItems.push({
              url: bestMp4.src,
              label: bestMp4.src.split("/").pop() || bestMp4.src,
            });
          }
        });
      }

      if (docType === "pdf") {
        await addVideoLinks();
      } else if (docType === "image") {
        await addVideoLinks();
      } else {
        addDocumentLink();
      }

      if (!linkItems.length) return;

      container.hidden = false;
      container.innerHTML =
        '<h3 class="record-related-media-title">Related Media</h3>' +
        '<ul class="record-related-media-list">' +
        linkItems
          .map(function (item) {
            return (
              '<li><a class="record-related-media-link" href="' +
              escapeHtml(item.url) +
              '" target="_blank" rel="noopener">' +
              escapeHtml(item.label) +
              "</a></li>"
            );
          })
          .join("") +
        "</ul>";
    }
    ///--> END NEW CODE - DYNAMIC VIDEO LOADING
  })();
