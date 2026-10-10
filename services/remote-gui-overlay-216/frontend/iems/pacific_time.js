// Every time the GUI shows is Pacific, whatever timezone the viewer's machine is in.
//
// The GUI formats dates with toLocaleString()/toLocaleTimeString() and
// Intl.DateTimeFormat without a timeZone, which means the browser's own zone.
// This module is imported by the IEMS plugin page, which the plugin loader
// evaluates eagerly at startup, so the default applies to every page. An
// explicit timeZone passed by any caller is still respected.
const PACIFIC = 'America/Los_Angeles';
const withZone = (options) =>
  (options && options.timeZone) ? options : Object.assign({}, options || {}, { timeZone: PACIFIC });

if (!Date.prototype.__pacificDefault) {
  ['toLocaleString', 'toLocaleDateString', 'toLocaleTimeString'].forEach((name) => {
    const original = Date.prototype[name];
    Date.prototype[name] = function pacific(locales, options) {
      return original.call(this, locales, withZone(options));
    };
  });
  const OriginalDTF = Intl.DateTimeFormat;
  const PacificDTF = function DateTimeFormat(locales, options) {
    return new OriginalDTF(locales, withZone(options));
  };
  PacificDTF.prototype = OriginalDTF.prototype;
  PacificDTF.supportedLocalesOf = OriginalDTF.supportedLocalesOf.bind(OriginalDTF);
  Intl.DateTimeFormat = PacificDTF;
  Object.defineProperty(Date.prototype, '__pacificDefault', { value: true });
}

export const DISPLAY_TIMEZONE = PACIFIC;
