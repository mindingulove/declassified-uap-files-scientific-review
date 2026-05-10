
        (async () => {
            const liveBadgeConfig = {"data":{"dvidsParams":{"eventFilterType":"man","toggleEventListMaxResults":true,"toggleUpcomingEventMaxResultView":true,"toggleLiveTodayEventMaxResultView":false,"toggleEventListToDateRange":false,"toggleEventHashtags":true,"toggleIncludeExternals":false,"toggleEventSort":true,"eventListMaxResults":"50","upcomingEventMaxResultView":"5","liveTodayEventMaxResultView":"3","eventListToDays":7,"includeExternals":false,"eventHashtags":"dgovlive","eventSort":"asc","autoplay":true,"manualSelectedEvents":"","showLiveNowList":true,"showLiveTodayList":true,"showUpcomingEventsList":true,"apiKey":"key-68bb60d16b35e","dvidsURL":"https://api.dvidshub.net/","dvidsStagingURL":null,"showTestVid":false,"showPanelWhenEmpty":false,"toDate":"2026-06-28T23:59:59.0000000-04:00","fromDate":"2026-05-09T18:35:34.6922408-04:00"},"dleDNNSettings":{"templateLayout":"Left","templateStyle":"DGOV","moduleMode":"Player","moduleTitle":"LIVE EVENTS","liveNowListTitle":"LIVE TODAY","liveNowDefaultText":"There are currently no events scheduled for today.","liveTodayListTitle":"LIVE TODAY","liveTodayDefaultText":"No Events Currently Scheduled","upcomingEventsListTitle":"UPCOMING EVENTS","upcomingEventsDefaultText":"There are currently no upcoming events scheduled.","countdownTitle":"UP NEXT","countdownTitleFuture":"UPCOMING EVENT","templateDisclaimer":"Having playback problems? \u003ca href=\"/News/Live-Events/\"\u003eClick here to refresh the page.\u003c/a\u003e If you continue to have issues, try changing to a different web browser.","videoBugPosition":"TopRight","showModuleTitle":false,"showEventTitle":true,"showEventDesc":true,"showCountdownTitle":true,"showCountdownDesc":true,"showVideoBug":false,"liveNowActiveClick":"on","liveNowActiveManualTime":"fifteenMin","toggleError":false,"selectedSMMSealId":2002859035,"selectedSeal":"https://media.defense.gov/2021/Sep/21/2002859035/400/400/0/210921-D-D0439-103.PNG","selectedSMMSealForErrorsId":2002859034,"selectedSealForErrors":"https://media.defense.gov/2021/Sep/21/2002859034/400/400/0/210921-D-D0439-102.PNG","selectedSMMCountdownBackgroundId":2002042277,"selectedBackground":"https://media.defense.gov/2018/Sep/19/2002042277/800/450/0/180919-D-MA852-001.JPG","selectedSMMNoEventBackgroundId":2002041905,"selectedNoEvent":"https://media.defense.gov/2018/Sep/18/2002041905/800/450/0/180918-D-MA852-004.JPG","selectedDVIDSVideoBugId":2002041896,"selectedVideoBug":"https://media.defense.gov/2018/Sep/18/2002041896/200/200/0/180918-D-MA852-002.PNG","dvidsVideoPlayerUrl":"https://www.war.gov/Multimedia/Videos?videoid=","dvidsLiveEventsUrl":"https://www.war.gov/News/LiveEvents/#/?currentVideo=","noEventMessage":"There are currently no scheduled events.","noEventsLink":"/Multimedia/Videos/","toggleLiveEventVideoBug":false,"liveEventVideoBugPosition":"TopRight","isBackend":false},"dleTestSettings":null}};

            new Vue({
                el:'#dle-live-badge-10b8b828-368e-439c-8257-5f02735a20da',
                data: {
                    isLiveNow: false,
                    videos: {
                        all: [],
                        liveNow: [],
                        liveToday: [],
                        liveLater: []
                    },
                    config: {},
                    dropdownStyles: {},
                    ddState: 0,
                    leadInText: '',
                    leadInTimeoutId: null,
                    leadInTimeoutOnce: false,
                },
                computed: {
                    buttonLabel: function () {
                        if (this.videos && this.videos.liveNow && this.videos.liveNow.length > 0)
                            return "Live Now";

                        if (this.videos && this.videos.liveToday && this.videos.liveToday.length > 0 && this.videos.liveLater.length === 0) {
                            return "Live Today";
                        }
                        return "Live Events";;
                    },
                },
                watch:{
                    'videos': function () {
                        const docBodyClassName = 'dle-has-live-events-badge';
                        if (this.videos && this.videos.all && this.videos.all.length > 0) {
                            document.body.classList.add(docBodyClassName);
                        } else {
                            document.body.classList.remove(docBodyClassName);
                        }
                    }
                },
                created() {
                    window.addEventListener("resize", this.liveBadgeResizeHandler);
                    window.addEventListener("scroll", this.liveBadgeResizeHandler);
                },
                destroyed() {
                    window.removeEventListener("resize", this.liveBadgeResizeHandler);
                    window.removeEventListener("resize", this.leadInTextResizeHandler);
                    window.removeEventListener("scroll", this.liveBadgeResizeHandler);
                },
                mounted: function () {
                    try {
                        this.config = {
                            dvids: liveBadgeConfig.data.dvidsParams,
                            dle: liveBadgeConfig.data.dleDNNSettings,
                            test: liveBadgeConfig.data.dleTestSettings
                        };
                        this.getVideos();
                    } catch (e) {
                        this.onBackend() && console.error(e);
                    }

                    if (this.config.test && this.config.test.testUseTestData) {
                        return;
                    }

                    setInterval(() => {
                        this.getVideos();
                    },
                        15000);
                },
                methods: {
                    getVideos: async function () {
                        let videoListObj = {};
                        try {
                            const dvidsParams = DLEApi.createDvidsParams(this.config.dvids);
                            if (this.config.test && this.config.test.testUseTestData) {
                                videoListObj = await DLEApi.getFakeVideoList(
                                    this.config.test.testLiveNowEventsCount,
                                    this.config.test.testLiveTodayEventsCount,
                                    this.config.test.testUpcomingEventsCount,
                                    this.config.test.testEventsJson,
                                    this.config.dvids.apiKey
                                );
                                videoListObj.videos = videoListObj.videos.slice(0, dvidsParams.max_results);
                            } else {
                                videoListObj = await DLEApi.getVideoList(dvidsParams);
                            }
                            this.videos = DLEApi.parseVideoList(videoListObj, this.config);
                            setTimeout(() => {
                                this.setupLeadIn();
                            },
                                100);

                        } catch (e) {
                            this.onBackend() && console.error(e);
                        }
                    },
                    setLiveBadgeWidth: function () {
                        let positioningEl;
                        try {
                            positioningEl = 'header .header-inner' ?
                                document.querySelector('header .header-inner') :
                                document.body;
                            if (positioningEl === null) {
                                positioningEl = document.body;
                            }
                        } catch (e) {
                            this.onBackend() && console.warn('DVIDS Live Events dropdown container not found. The error is:', e);
                            positioningEl = document.body;
                        }
                        try {
                            const ppos = positioningEl.getBoundingClientRect();
                            const dd = document.querySelector('.dle-live-badge-dropdown');

                            if (dd.style.display === "block") return;

                            dd.style.visibility = 'hidden';
                            dd.style.display = 'block';
                            dd.style.width = 'auto';
                            dd.style.marginLeft = 0;
                            const ddRect = dd.getBoundingClientRect();
                            dd.style.display = 'none';
                            dd.style.visibility = 'visible';
                            let newWidth = Math.abs(ppos.right - ddRect.left);
                            const minWidth = ddRect.width;

                            if (newWidth < minWidth) {
                                newWidth = minWidth;
                            }

                            let newLeft = 0;
                            if (ddRect.x + newWidth > document.body.clientWidth) {
                                newLeft = document.body.clientWidth - ddRect.x - newWidth;
                            }

                            dd.style.width = newWidth + 'px';
                            dd.style.marginLeft = newLeft + 'px';

                        } catch (e) {
                            this.onBackend() && console.error('DVIDS Live Events error:', e);
                        }
                    },
                    liveBadgeResizeHandler: function () {
                        if (this.ddState === 0)
                            return;
                        this.manualStateChange();
                    },
                    manualStateChange: function () {
                        const vm = this;

                        if (vm.ddState === 0) {
                            $('body').addClass('dle-dd-open');
                            vm.ddState = 1;
                            vm.dropdownStyles = {
                                ...vm.dropdownStyles,
                                display: 'block',
                            };
                        } else if (vm.ddState === 1) {
                            vm.ddState = 0;
                            vm.dropdownStyles = {
                                ...vm.dropdownStyles,
                                display: 'none',
                            };
                            $('body').removeClass('dle-dd-open');
                        }
                    },
                    handleBadgeKeyDown: function (event) {
                        if (!event) return;
                        if ((event.target.id === 'dle-live-badge-10b8b828-368e-439c-8257-5f02735a20da-tab-before' && event.key.toUpperCase() === 'TAB' && !event.shiftKey) ||
                            (event.target.id === 'dle-live-badge-10b8b828-368e-439c-8257-5f02735a20da-tab-after' && event.key.toUpperCase() === 'TAB' && event.shiftKey))
                            event.preventDefault();
                    },
                    handleBadgeKeyUp: function (event) {
                        if (!event) return;
                        event.preventDefault();
                        const vm = this;
                        this.setLiveBadgeWidth();
                        this.manualStateChange();
                        if (vm.ddState === 1) {
                            setTimeout(() => {
                                if (event.key.toUpperCase() === 'TAB' && !event.shiftKey) {
                                    $(".dle-live-badge-dropdown a:first").focus();
                                } else {
                                    $(".dle-live-badge-dropdown a:last").focus();
                                }
                                $(".dle-live-badge-dropdown a:first").off();
                                $(".dle-live-badge-dropdown a:first").on('keydown',
                                    function (e) {
                                        if (e.shiftKey && e.key.toUpperCase() === 'TAB') {
                                            e.preventDefault();

                                            $('#dle-live-badge-10b8b828-368e-439c-8257-5f02735a20da-tab-before').focus();
                                        }
                                    });
                            },
                                50);

                            $(".dle-live-badge-dropdown a:last").off();
                            $(".dle-live-badge-dropdown a:last").on('keydown',
                                function (e) {
                                    if (e.key.toUpperCase() === 'TAB' && !e.shiftKey) {
                                        e.preventDefault();
                                        $('#dle-live-badge-10b8b828-368e-439c-8257-5f02735a20da-tab-after').focus();

                                    }
                                });
                        }

                    },
                    handleBadgeClick: function () {
                        if (!window.matchMedia('(max-width: 768px)').matches) {
                            try {
                                window.location.href = this.config.dle.dvidsLiveEventsUrl;
                            } catch (e) {
                                this.onBackend() && console.error('DVIDS Live Events error: ', e);
                            }
                        }
                        if (this.ddState === 0) {
                            this.setLiveBadgeWidth();
                        }
                        this.manualStateChange();

                    },
                    setupLeadIn: function () {
                        if (!this.videos || !this.videos.all || this.videos.all.length === 0) {
                            return;
                        }
                        this.leadInText = this.videos.all[0].title;
                        window.removeEventListener("resize", this.leadInTextResizeHandler);
                        window.addEventListener("resize", this.leadInTextResizeHandler);
                        this.checkLeadInWidth();
                    },
                    checkLeadInWidth: function () {
                        const vm = this;
                        $(this.$el).find('.lead-in-event .event-title-text').each(function () {
                            let el = this;
                            el.innerText = vm.leadInText;
                            el.style.whiteSpace = "nowrap";
                            el.style.overflow = "visible";
                            const oneLineBounds = el.getBoundingClientRect();
                            el.style.whiteSpace = "normal";
                            const nLinesBounds = el.getBoundingClientRect();
                            if (nLinesBounds.height > oneLineBounds.height) {
                                const splitText = vm.leadInText.split(' ');
                                for (let i = 0; i < splitText.length; i++) {
                                    const newText = splitText.slice(0, splitText.length - 1 - i);
                                    el.innerText = newText.join(' ') + '...';
                                    const newTextBounds = el.getBoundingClientRect();
                                    if (newTextBounds.height <= oneLineBounds.height) {
                                        break;
                                    }
                                }
                            }
                            el.style.overflow = "hidden";
                            el.style.opacity = 1;
                        });
                    },
                    leadInTextResizeHandler: function () {
                        const vm = this;
                        // Clear the debounce timer
                        clearTimeout(vm.leadInTimeoutId);
                        // Debounce timer
                        vm.leadInTimeoutId = setTimeout(() => {
                            vm.checkLeadInWidth();
                            vm.leadInTimeoutOnce = false;
                        }, 10);

                        // Run once immediately
                        if (!vm.leadInTimeoutOnce) {
                            vm.checkLeadInWidth();
                            vm.leadInTimeoutOnce = true;
                        }
                    },
                    onBackend: function () {
                        return this.config && this.config.dle && this.config.dle.isBackend;
                    }
                }
            });
        })();
