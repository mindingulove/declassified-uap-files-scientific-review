
    var usasearch_config = {
        siteHandle: skinvars.aid,
        autoSubmitOnSelect: false,
    }

    window.onload = function () {
        document.getElementById("footer-search-input").value = "";
    }

    var script = document.createElement("script");
    script.type = "text/javascript";
    script.src = "//search.usa.gov/javascripts/remote.loader.js";
    document.getElementsByTagName("head")[0].appendChild(script);

    (function ($) {
        $(function () {
            $('.footer-nav-col h3').click(function () {
                if (window.innerWidth > 991) return;
                $(this).parent('.footer-nav-col').toggleClass('active');
            });
        });
    })(jQuery);

    const queryInput = $("input[name=search-main],input[name=header-search], input[name=footer-search], i[id=fa-search-icon-bottom]").on("keyup", function (e) {
        if (e.keyCode == 13) {
            submitSearch($(this));
        }
    });

    $("input[name=search-main] ~ button, .search-icon, input[name=footer-search], input[name=footer-search] ~ button, i[id=fa-search-icon-bottom]").on("click", function (e) {
        e.stopImmediatePropagation();
        submitSearch($(this));
    });

    $(".search-icon").on("keypress", function (e) {
        if (e.which == 13) {
            e.stopImmediatePropagation();
            submitSearch($(this));
        }
    });

    function submitSearch($this) {
        const query = $this ? ($this.val() || $this.parent().find('input').val()) : "";
        const affiliate = !!skinvars.aid ? skinvars.aid : 'defensegov';
        if (query.length > 1)
            window.location = "//search.usa.gov/search?query=" + DOMPurify.sanitize(query) + "&affiliate=" + affiliate + "&utf8=%26%23x2713%3B";
    }
