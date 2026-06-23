// Netflix Clone JavaScript

// Search functionality
function searchMovies() {
    const query = document.getElementById('search').value;
    if (query.length > 2) {
        window.location.href = `/search?q=${encodeURIComponent(query)}`;
    }
}

// Add event listener for search input
document.addEventListener('DOMContentLoaded', function() {
    const searchInput = document.getElementById('search');
    if (searchInput) {
        searchInput.addEventListener('keypress', function(e) {
            if (e.key === 'Enter') {
                searchMovies();
            }
        });
    }
});

// Smooth scrolling for movie sliders
document.addEventListener('DOMContentLoaded', function() {
    const sliders = document.querySelectorAll('.movie-slider');
    sliders.forEach(slider => {
        slider.addEventListener('wheel', function(e) {
            e.preventDefault();
            slider.scrollLeft += e.deltaY;
        });
    });
});

// Hover effects for movie cards
document.addEventListener('DOMContentLoaded', function() {
    const movieCards = document.querySelectorAll('.movie-card');
    movieCards.forEach(card => {
        card.addEventListener('mouseenter', function() {
            this.style.transform = 'scale(1.05)';
        });
        card.addEventListener('mouseleave', function() {
            this.style.transform = 'scale(1)';
        });
    });
});

// Filter functionality for movies page
document.addEventListener('DOMContentLoaded', function() {
    const filterTabs = document.querySelectorAll('.filter-tab');
    const movieCards = document.querySelectorAll('.movie-card');

    filterTabs.forEach(tab => {
        tab.addEventListener('click', function() {
            // Remove active class from all tabs
            filterTabs.forEach(t => t.classList.remove('active'));
            // Add active class to clicked tab
            this.classList.add('active');

            const filter = this.getAttribute('data-filter');

            movieCards.forEach(card => {
                if (filter === 'all' || card.getAttribute('data-category') === filter) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        });
    });

    // Search functionality for movies page
    const searchInput = document.querySelector('.search-input');
    if (searchInput) {
        searchInput.addEventListener('input', function() {
            const query = this.value.toLowerCase();
            movieCards.forEach(card => {
                const title = card.querySelector('h3').textContent.toLowerCase();
                if (title.includes(query)) {
                    card.style.display = 'block';
                } else {
                    card.style.display = 'none';
                }
            });
        });
    }
});

// Hero Slider Functionality
document.addEventListener('DOMContentLoaded', function() {
    const sliderContainer = document.querySelector('.slider-container');
    if (!sliderContainer) return;

    const slides = document.querySelectorAll('.slide');
    const dots = document.querySelectorAll('.dot');
    const prevBtn = document.querySelector('.slider-prev');
    const nextBtn = document.querySelector('.slider-next');

    let currentSlide = 0;
    let slideInterval;

    function showSlide(index) {
        slides.forEach(slide => slide.classList.remove('active'));
        dots.forEach(dot => dot.classList.remove('active'));

        slides[index].classList.add('active');
        dots[index].classList.add('active');
        currentSlide = index;
    }

    function nextSlide() {
        currentSlide = (currentSlide + 1) % slides.length;
        showSlide(currentSlide);
    }

    function prevSlide() {
        currentSlide = (currentSlide - 1 + slides.length) % slides.length;
        showSlide(currentSlide);
    }

    function startAutoPlay() {
        slideInterval = setInterval(nextSlide, 5000); // 5 seconds
    }

    function stopAutoPlay() {
        clearInterval(slideInterval);
    }

    // Event listeners
    if (nextBtn) nextBtn.addEventListener('click', nextSlide);
    if (prevBtn) prevBtn.addEventListener('click', prevSlide);

    dots.forEach((dot, index) => {
        dot.addEventListener('click', () => showSlide(index));
    });

    // Pause on hover
    const slider = document.querySelector('.hero-slider');
    if (slider) {
        slider.addEventListener('mouseenter', stopAutoPlay);
        slider.addEventListener('mouseleave', startAutoPlay);
    }

    // Initialize
    if (slides.length > 0) {
        showSlide(0);
        startAutoPlay();
        const slider = document.querySelector('.hero-slider');
        if (slider) {
            slider.classList.remove('loading');
        }
    }
});