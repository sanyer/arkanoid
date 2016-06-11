"""
Entry point module for running Arkanoid.
"""
import logging
import math
import os
import random
import sys

import pygame

logging.basicConfig()
LOG = logging.getLogger('arkanoid')
LOG.setLevel(logging.DEBUG)

GAME_SPEED = 60  # In fps
DISPLAY_SIZE = 600, 650
DISPLAY_CAPTION = 'Arkanoid'
BALL_START_ANGLE_RAD = 5.0
# The speed that the ball will always try to arrive at.
BALL_BASE_SPEED = 8  # pixels per-frame
# The max speed of the ball, prevents a runaway speed when lots of rapid
# collisions.
BALL_MAX_SPEED = 15  # pixels per-frame
# Per-frame rate at which ball is brought back to base speed.
BALL_SPEED_NORMALISATION_RATE = 0.02
# Increase in speed caused by colliding with a brick.
BRICK_SPEED_ADJUST = 0.5
# Increase in speed caused by colliding with a wall.
WALL_SPEED_ADJUST = 0.2
# The speed the paddle moves.
PADDLE_SPEED = 10


class Paddle(pygame.sprite.Sprite):
    """The movable paddle used to control the ball."""

    # TODO: Need a "bonus collision action" which can be added to the paddle
    # and the paddle invokes the callback when a bonus is struck. This can
    # be less generic than the "collidable object" concept the ball has,
    # because the bonuses are the only thing to strike the paddle (apart from
    # the ball).
    # TODO: offsets and speed should be passed via initialiser

    def __init__(self, speed=10):
        super().__init__()
        self.image, self.rect = load_png('paddle.png')
        screen = pygame.display.get_surface()
        self._area = screen.get_rect()
        self.rect.midbottom = self._area.midbottom
        self.rect.top -= 50
        self._offset = 0
        self._speed = speed

    def update(self):
        # Continuously move the paddle when the offset is non-zero.
        newpos = self.rect.move(self._offset, 0)
        if self._area.contains(newpos):
            # But only update the position of the paddle if it's within
            # the screen area.
            self.rect = newpos

    def move_left(self):
        # Set the offset to negative to move left.
        self._offset = -self._speed

    def move_right(self):
        # A positive offset to move right.
        self._offset = self._speed

    def stop(self):
        self._offset = 0

    @staticmethod
    def bounce_strategy(paddle_rect, ball_rect):
        """Implementation of a ball bounce strategy used to calculate
        the angle that the ball bounces off the paddle. The angle
        of bounce is dependent upon where the ball strikes the paddle.

        Note: this function is not tied to the Paddle class but we house it
        here as it seems a reasonable place to keep it.

        Args:
            paddle_rect:
                The Rect of the paddle.
            ball_rect:
                The Rect of the ball.

        Returns:
            The angle of bounce in radians.
        """
        # TODO: this may need to return a tuple of (angle, speed_level) where
        # speed_level is say, SLOW, NORMAL or FAST, and the Ball will then
        # interpret that by modifying the actual speed appropriately.
        # TODO: angles are too oblique at the ends. Reduce overall angle range

        # Break the paddle into 8 segments. Each segment triggers a different
        # angle of bounce.
        segment_size = paddle_rect.width // 8
        segments = []

        for i in range(8):
            # Create rectangles for the first 7 segments.
            left = paddle_rect.left + segment_size * i
            if i < 7:
                # The first 7 segments are a fixed size.
                segment = pygame.Rect(left, paddle_rect.top, segment_size,
                                      paddle_rect.height)
            else:
                # The last segment makes up what is left of the paddle width.
                segment = pygame.Rect(left, paddle_rect.top,
                                      paddle_rect.width - (segment_size * 7),
                                      paddle_rect.height)
            segments.append(segment)

        # The bounce angles corresponding to each of the 8 segments.
        angles = -135, -120, -110, -100, -80, -70, -60, -45

        # Discover which segment the ball collided with. Just use the first.
        index = ball_rect.collidelist(segments)

        # Return the angle adding a small amount of randomness.
        # The randomness prevents the ball from getting stuck in a
        # repeating bounce pattern off the paddle.
        return math.radians(angles[index] + random.randint(-5, 5))


class Ball(pygame.sprite.Sprite):
    """The ball that bounces around the screen.

    A Ball is aware of the screen, and any collidable objects in the screen
    that have been added via add_collidable_object(). Where no collidable
    objects have been added, a Ball will just travel from its start point
    straight off the edge of the screen calling an off_screen_callback if
    one has been set. It is up to clients to add the necessary collidable
    objects to keep the Ball within the confines of the screen.

    A Ball will collide with objects that it is told about via
    add_collidable_object(). It will follow normal physics when bouncing
    off an object, but this can be overriden by passing a bounce strategy
    with a collidable object when it is added to the Ball. See
    add_collidable_object() for further details.
    """

    def __init__(self, start_pos, start_angle, base_speed, max_speed=15,
                 normalisation_rate=0.02,
                 off_screen_callback=None):
        """
        Initialise a new Ball with the given arguments. If supplied,
        the off_screen_callback will be invoked whenever the Ball leaves
        the screen. This is a no-args callable.

        Args:
            start_pos:
                The starting position of the ball (coordinates).
            start_angle:
                The starting angle of the ball in radians taken against the
                x axis.
            base_speed:
                The baseline speed of the ball. Collisions with objects may
                increase/decrease the speed of the ball, but the speed will
                never fall below the base speed.
            max_speed
                The maximum permitted speed of the ball. Collisions with
                objects may increase the speed of the ball, but the speed
                will never go above the max_speed.
            normalisation_rate:
                The per-frame rate at which the ball is brought back to base
                speed, should the speed have changed by colliding with
                something.
            off_screen_callback:
                A no-args callable that will be called if the ball goes off
                the edge of the screen.
        """
        super().__init__()
        self._angle = start_angle
        self._speed = base_speed
        self._max_speed = max_speed
        self._normalisation_rate = normalisation_rate
        self.image, self.rect = load_png('ball.png')
        self.rect.midbottom = start_pos
        screen = pygame.display.get_surface()
        self._area = screen.get_rect()
        self._collidable_objects = []
        self._off_screen_callback = off_screen_callback

    def add_collidable_object(self, obj, bounce_strategy=None,
                              speed_adjust=0.0, on_collide=None):
        """Add an object that the ball might collide with. The object should
        be a Rect for static objects, or a Sprite for animated objects.

        A bounce strategy can be supplied to override the default bouncing
        behaviour of the ball whenever it strikes the object being added.
        The strategy should be a callable that will receive two arguments:
        the Rect of the object being struck, and the Rect of the ball. It
        should return the angle of bounce in radians. If not supplied, the
        ball will conform to normal physics when bouncing off the object.

        In addition, an optional collision callable can be supplied together
        with the object being added. This will  be invoked to perform an
        action whenever the ball strikes the object. The callable takes two
        arguments: the Rect of the object and the Rect of the ball.

        Args:
            obj:
                The collidable object. A Rect for static objects,
                or a Sprite for animated objects.
            bounce_strategy:
                Optional callable that determines how the ball should bounce
                when it collides with the object. It takes 2 arguments: the
                Rect of the object and the Rect of the ball.
            speed_adjust:
                Optional numeric value that will be used to speed up or slow
                down the the ball. Use a negative value to slow the ball down.
            on_collide:
                Optional callable that will be called when a collision occurs.
                It takes 1 argument: the Rect of the object struck.
        """
        self._collidable_objects.append(
            (obj, bounce_strategy, speed_adjust, on_collide))

    def remove_collidable_object(self, obj):
        """Remove an object so that the ball can no longer collide with it.

        Args:
            obj:
                The collidable object to remove - either the Rect or Sprite.
        """
        self._collidable_objects = [o for o in self._collidable_objects if
                                    o[0] != obj]

    def update(self):
        """Update the ball. Check whether the ball has collided with
        anything and if so, update its angle and speed and invoke any
        associated actions.
        """
        # Get the new position of the ball.
        self.rect = self._calc_new_pos()

        if self._area.contains(self.rect):
            # The ball is still on the screen.
            # Find out if the ball has collided with anything.
            # We have to get these on the fly, as the rects of sprites change.
            collidable_rects = self._get_collidable_rects()
            indexes = self.rect.collidelistall(collidable_rects)

            if indexes:
                # There's been a collision - find out with what.
                self._handle_collision(collidable_rects, indexes)
            else:
                # No collision. Bring speed back to base.
                self._normalise_speed()
        else:
            # Ball has gone off the screen.
            # Invoke the callback if we have one.
            if self._off_screen_callback:
                self._off_screen_callback()

    def _calc_new_pos(self):
        offset_x = self._speed * math.cos(self._angle)
        offset_y = self._speed * math.sin(self._angle)

        return self.rect.move(offset_x, offset_y)

    def _get_collidable_rects(self):
        """Get the Rects of the collidable objects. Note that these have to
        be dynamically obtained, because in the case of sprites the Rects
        are continually changing.
        """
        rects = []
        for obj, _, _, _ in self._collidable_objects:
            try:
                # obj might be a Sprite with a rect attribute
                rects.append(obj.rect)
            except AttributeError:
                # obj is already a rect
                rects.append(obj)
        return rects

    def _handle_collision(self, collidable_rects, indexes):
        rects, actions, speed_adjust = [], [], 0

        for i in indexes:
            rects.append(collidable_rects[i])
            actions.append(self._collidable_objects[i][3])
            speed_adjust += self._collidable_objects[i][2]

        if len(rects) == 1:
            # Collision with a single object.
            bounce_strategy = self._collidable_objects[indexes[0]][1]
            if bounce_strategy:
                # We have a bounce strategy, so use that.
                self._angle = bounce_strategy(rects[0], self.rect)
            else:
                # Use the default calculation for the angle.
                self._angle = self._calc_new_angle(rects)
        else:
            # Collision with more than one object.
            # Use the default calculation for the angle.
            self._angle = self._calc_new_angle(rects)

        for i in range(len(actions)):
            # Invoke the collision callbacks
            on_collide = actions[i]
            if on_collide:
                on_collide(rects[i])

        # Adjust the speed based on what we collided with.
        if self._speed < self._max_speed:
            self._speed += speed_adjust
        LOG.debug('Ball speed: %s', self._speed)

    def _normalise_speed(self):
        if self._speed > BALL_BASE_SPEED:
            self._speed -= self._normalisation_rate
        else:
            self._speed += self._normalisation_rate

    def _calc_new_angle(self, rects):
        """Calculate the default angle of bounce of the ball, given a
        sequence of rectangles that the ball collided with.
        """
        if len(rects) == 3:
            # Collision where 3 bricks join causes the ball to bounce back
            # in the direction it originated.
            LOG.debug('3 brick collision')
            angle = self._angle + math.pi
        else:
            # Has to have collided with max 2 objects. Find out how
            # many points of the ball's rect are in contact.
            tl, tr, bl, br = False, False, False, False

            for rect in rects:
                tl = tl or rect.collidepoint(self.rect.topleft)
                tr = tr or rect.collidepoint(self.rect.topright)
                bl = bl or rect.collidepoint(self.rect.bottomleft)
                br = br or rect.collidepoint(self.rect.bottomright)

            if (tl and tr) or (bl and br):
                # Top of the ball has collided with the bottom of an object,
                # or bottom of the ball has collided with the top of an object.
                LOG.debug('Top/bottom collision')
                angle = -self._angle
            elif sum((tl, tr, bl, br)) == 1:
                # Ball has hit the corner of an object - bounce it back in
                # the direction from which it originated.
                LOG.debug('Corner collision')
                angle = self._angle + math.pi
            else:
                # Ball has hit the side of an object.
                LOG.debug('Side collision')
                angle = math.pi - self._angle

        # Add small amount of randomness +/-3 degrees (+/- 0.05 rad)
        angle += random.uniform(-0.05, 0.05)
        LOG.debug(angle)

        return angle


def load_png(filename):
    """Load a png image with the specified filename from the
    data/graphics directory and return it and its Rect.

    Args:
        filename:
            The filename of the image.
    Returns:
        A 2-tuple of the image and its Rect.
    """
    image = pygame.image.load(
        os.path.join('data', 'graphics', filename))
    if image.get_alpha is None:
        image = image.convert()
    else:
        image = image.convert_alpha()
    return image, image.get_rect()


def run_game():
    # TODO: turn this into an Arkenoid class with a main_loop()
    # TODO: doc on

    # TODO: Introduce concept of Level (or perhaps "Round").
    # This will be a base class with
    # specialisations for each concrete level. Levels will setup bricks
    # in __init__(screen) and have attributes "lives", "bricks",
    # "background" (or possibly just "collidable_objects"). Common
    # functionality can live in base class. Actually, "lives" will be a game
    # attribute not a level attribute?

    # Initialise the screen.
    pygame.init()
    screen = create_screen()

    # Create the background
    background = create_background(screen)

    # Create the edges of the game area.
    left, right, top = create_edges(background)

    # Blit the background to the screen.
    screen.blit(background, (0, 0))

    # Initialise the sprites.
    paddle = Paddle(speed=PADDLE_SPEED)
    paddlesprite = pygame.sprite.RenderPlain(paddle)

    ball = Ball(start_pos=paddle.rect.midtop,
                start_angle=BALL_START_ANGLE_RAD,
                base_speed=BALL_BASE_SPEED,
                max_speed=BALL_MAX_SPEED,
                normalisation_rate=BALL_SPEED_NORMALISATION_RATE,
                off_screen_callback=off_screen)

    # Let the ball know about the objects it might collide with.
    ball.add_collidable_object(left, speed_adjust=WALL_SPEED_ADJUST)
    ball.add_collidable_object(right, speed_adjust=WALL_SPEED_ADJUST)
    ball.add_collidable_object(top, speed_adjust=WALL_SPEED_ADJUST)
    ball.add_collidable_object(paddle, bounce_strategy=paddle.bounce_strategy)

    # Create the bricks.
    bricks = create_bricks(screen)

    def on_brick_collide(brick):
        ball.remove_collidable_object(brick)
        screen.blit(background, brick, brick)

    for brick in bricks:
        # Make the ball aware of the bricks it might collide with. Every
        # brick collision slightly increases the speed of the ball.
        ball.add_collidable_object(brick, speed_adjust=BRICK_SPEED_ADJUST,
                                   on_collide=on_brick_collide)

    ballsprite = pygame.sprite.RenderPlain(ball)

    # Display all updates.
    pygame.display.flip()

    # Initialise the clock.
    clock = pygame.time.Clock()

    running = True

    while running:
        # Clock runs at 60 fps.
        clock.tick(GAME_SPEED)

        # Monitor for key presses.
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_LEFT:
                    paddle.move_left()
                elif event.key == pygame.K_RIGHT:
                    paddle.move_right()
            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_LEFT or event.key == pygame.K_RIGHT:
                    paddle.stop()

        # Erase the previous location of the sprites.
        paddlesprite.clear(screen, background)
        ballsprite.clear(screen, background)

        # Update the state of the sprites and redraw them.
        paddlesprite.update()
        paddlesprite.draw(screen)
        ballsprite.update()
        ballsprite.draw(screen)

        pygame.display.flip()

    LOG.info('Exiting')


def create_screen():
    screen = pygame.display.set_mode(DISPLAY_SIZE)
    pygame.display.set_caption(DISPLAY_CAPTION)
    pygame.mouse.set_visible(False)
    return screen


def create_background(screen):
    background = pygame.Surface(screen.get_size())
    background = background.convert()
    background.fill((0, 0, 0))
    return background


def create_edges(background):
    edge, _ = load_png('edge.png')
    left_rect = background.blit(edge, (0, 0))
    right_rect = background.blit(edge, (DISPLAY_SIZE[0] - edge.get_width(), 0))
    top_edge, _ = load_png('top.png')
    top_rect = background.blit(top_edge, (edge.get_width(), 0))
    return left_rect, right_rect, top_rect


def create_bricks(screen):
    # TODO: this will be moved into each level subclass called by __init__()
    # to populate a level.bricks attribute. Adjust pixel dimensions for better
    # graphics.
    bricks = []
    colours = 'green', 'blue', 'yellow', 'red', 'grey'
    top = 200

    for colour in colours:
        brick, _ = load_png('brick_{}.png'.format(colour))
        left = 15
        for i in range(13):
            # 13 bricks are added horizontally
            rect = screen.blit(brick, (left, top))
            left += 44
            bricks.append(rect)
        top -= 22

    return bricks


def off_screen():
    sys.exit()


if __name__ == '__main__':
    run_game()
