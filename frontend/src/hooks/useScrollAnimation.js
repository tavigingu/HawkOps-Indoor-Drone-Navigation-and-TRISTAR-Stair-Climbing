import { useState, useEffect, useCallback } from 'react';

// Scroll-driven animation hook (scrollY, direction, progress, current section).
export function useScrollAnimation() {
  const [scrollY, setScrollY] = useState(0);
  const [scrollDirection, setScrollDirection] = useState('down');
  const [scrollProgress, setScrollProgress] = useState(0);
  const [currentSection, setCurrentSection] = useState(0);

  const handleScroll = useCallback(() => {
    const currentScrollY = window.scrollY;
    const documentHeight = document.documentElement.scrollHeight - window.innerHeight;

    setScrollDirection(currentScrollY > scrollY ? 'down' : 'up');

    const progress = documentHeight > 0 ? (currentScrollY / documentHeight) * 100 : 0;
    setScrollProgress(progress);

    const sectionHeight = window.innerHeight;
    const section = Math.floor(currentScrollY / sectionHeight);
    setCurrentSection(section);

    setScrollY(currentScrollY);
  }, [scrollY]);

  useEffect(() => {
    window.addEventListener('scroll', handleScroll, { passive: true });
    return () => window.removeEventListener('scroll', handleScroll);
  }, [handleScroll]);

  return { scrollY, scrollDirection, scrollProgress, currentSection };
}

// Parallax translate based on scroll position.
export function useParallax(speed = 0.5) {
  const { scrollY } = useScrollAnimation();
  return { transform: `translateY(${scrollY * speed}px)` };
}

// Reveal-on-scroll via IntersectionObserver.
export function useFadeInOnScroll(threshold = 0.1) {
  const [isVisible, setIsVisible] = useState(false);
  const [elementRef, setElementRef] = useState(null);

  useEffect(() => {
    if (!elementRef) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) setIsVisible(true);
      },
      { threshold }
    );
    observer.observe(elementRef);
    return () => {
      if (elementRef) observer.unobserve(elementRef);
    };
  }, [elementRef, threshold]);

  return [setElementRef, isVisible];
}

// Typewriter effect.
export function useTypingEffect(text, speed = 100) {
  const [displayedText, setDisplayedText] = useState('');
  const [isComplete, setIsComplete] = useState(false);

  useEffect(() => {
    let index = 0;
    setDisplayedText('');
    setIsComplete(false);

    const timer = setInterval(() => {
      if (index < text.length) {
        setDisplayedText(text.slice(0, index + 1));
        index++;
      } else {
        setIsComplete(true);
        clearInterval(timer);
      }
    }, speed);

    return () => clearInterval(timer);
  }, [text, speed]);

  return { displayedText, isComplete };
}
