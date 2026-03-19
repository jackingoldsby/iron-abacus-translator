import React, { useState } from 'react';
import './Tooltip.css';

/**
 * Tooltip Component
 *
 * Displays rich contextual information on hover.
 * Automatically positions to avoid edge overflow.
 */
function Tooltip({ children, content, disabled = false }) {
  const [isVisible, setIsVisible] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });

  const handleMouseEnter = (e) => {
    if (disabled) return;

    const rect = e.currentTarget.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;

    // Calculate initial position (below the element, centered)
    let top = rect.bottom + 8;
    let left = rect.left + rect.width / 2;

    // Adjust if tooltip would go off right edge
    const tooltipWidth = 320; // Approximate tooltip width
    if (left + tooltipWidth / 2 > viewportWidth - 20) {
      left = viewportWidth - tooltipWidth - 20;
    }

    // Adjust if tooltip would go off left edge
    if (left - tooltipWidth / 2 < 20) {
      left = 20 + tooltipWidth / 2;
    }

    // Adjust if tooltip would go off bottom edge (show above instead)
    const tooltipHeight = 200; // Approximate tooltip height
    if (top + tooltipHeight > viewportHeight - 20) {
      top = rect.top - tooltipHeight - 8;
    }

    setPosition({ top, left });
    setIsVisible(true);
  };

  const handleMouseLeave = () => {
    setIsVisible(false);
  };

  return (
    <div
      className="tooltip-wrapper"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {children}
      {isVisible && !disabled && (
        <div
          className="tooltip-content"
          style={{
            position: 'fixed',
            top: `${position.top}px`,
            left: `${position.left}px`,
            transform: 'translateX(-50%)'
          }}
        >
          {content}
        </div>
      )}
    </div>
  );
}

export default Tooltip;
